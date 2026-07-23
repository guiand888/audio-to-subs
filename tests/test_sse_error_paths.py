"""Tests for SSE stream error paths (M6 error-path coverage).

Targets the error branches in ``_event_generator`` and ``_redis_listener_coro``
that the route-wiring tests in ``test_api_jobs_stream.py`` don't reach:

- client disconnect (break path + cleanup)
- unexpected exception inside the generator loop
- generator cancellation (CancelledError path)
- malformed Redis message JSON
- Redis listener transport error
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sse_starlette.sse import ServerSentEvent

from audio_to_subs.api.routes import stream as stream_module
from audio_to_subs.api.routes.stream import _event_generator, _redis_listener_coro


class TestEventGeneratorErrorPaths:
    @pytest.mark.asyncio
    async def test_breaks_on_disconnect(self):
        """An already-disconnected client yields nothing and cleans up."""
        controlled: asyncio.Queue = asyncio.Queue()
        with patch.object(
            stream_module, "_subscribe_job_stream", return_value=controlled
        ):
            request = MagicMock()
            request.is_disconnected = MagicMock(return_value=True)

            events = [
                e async for e in _event_generator(request, job_id="abc", redis=None)
            ]

        assert events == []

    @pytest.mark.asyncio
    async def test_unexpected_exception_is_swallowed(self):
        """An exception from is_disconnected is caught and logged, not raised."""
        controlled: asyncio.Queue = asyncio.Queue()
        with patch.object(
            stream_module, "_subscribe_job_stream", return_value=controlled
        ):
            request = MagicMock()

            async def _boom():
                raise RuntimeError("disconnect check failed")

            request.is_disconnected = _boom

            events = [
                e async for e in _event_generator(request, job_id="abc", redis=None)
            ]

        assert events == []

    @pytest.mark.asyncio
    async def test_cleanup_cancels_redis_listener_on_close(self):
        """Closing the generator (e.g. on client disconnect) must cancel the
        background Redis listener task and run the unsubscribe cleanup."""
        controlled: asyncio.Queue = asyncio.Queue()
        await controlled.put({"type": "progress", "value": 1})

        created_tasks: list[asyncio.Task] = []
        real_create = asyncio.create_task

        def _spy(coro, *args, **kwargs):
            task = real_create(coro, *args, **kwargs)
            created_tasks.append(task)
            return task

        with (
            patch.object(
                stream_module, "_subscribe_job_stream", return_value=controlled
            ),
            patch("asyncio.create_task", _spy),
        ):
            request = MagicMock()

            async def _ok_disconnect():
                return False

            request.is_disconnected = _ok_disconnect

            redis = MagicMock()
            pubsub = MagicMock()
            pubsub.subscribe = AsyncMock()
            pubsub.get_message = AsyncMock(
                side_effect=lambda *a, **k: asyncio.sleep(30)
            )
            pubsub.unsubscribe = AsyncMock()
            pubsub.close = AsyncMock()
            redis.pubsub.return_value = pubsub

            gen = _event_generator(request, job_id="abc", redis=redis)
            await gen.__anext__()  # consume the queued event

            listener_tasks = [t for t in created_tasks if isinstance(t, asyncio.Task)]
            assert listener_tasks, "Redis listener task should have been created"

            await gen.aclose()
            await asyncio.sleep(0)  # let the cancel propagate

            assert listener_tasks[0].cancelled() or listener_tasks[0].done()


class TestRedisListenerErrorPaths:
    @pytest.mark.asyncio
    async def test_malformed_redis_message_is_skipped(self):
        """A non-JSON message is logged and skipped; the listener keeps going.

        Note: the listener now also queues a single ``stream_ready`` frame
        right after ``subscribe`` completes (race fix for the refresh flow).
        That frame is legitimate, so we drain it before asserting the queue
        is empty - the assertion is about the malformed message NOT being
        forwarded, not about the queue being totally empty.
        """
        queue: asyncio.Queue = asyncio.Queue()

        class _Pubsub:
            def __init__(self):
                self.unsubscribed = False
                self.closed = False
                self._calls = 0

            async def subscribe(self, *channels):
                pass

            async def get_message(self, timeout=1.0):
                self._calls += 1
                if self._calls == 1:
                    return {"type": "message", "data": "not-json"}
                # Second call blocks; the test cancels before it returns.
                await asyncio.sleep(30)
                return None

            async def unsubscribe(self):
                self.unsubscribed = True

            async def close(self):
                self.closed = True

        redis = MagicMock()
        pubsub = _Pubsub()
        redis.pubsub.return_value = pubsub

        task = asyncio.create_task(
            _redis_listener_coro(redis, queue, ["jobs:global"], "cid")
        )
        await asyncio.sleep(0.1)
        # Drain the legitimate stream_ready frame queued right after subscribe.
        assert queue.qsize() == 1
        ready = queue.get_nowait()
        assert ready == {"event": "stream_ready"}
        # After draining stream_ready, the malformed message must NOT have
        # been forwarded (queue stays empty).
        assert queue.empty()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert pubsub.unsubscribed is True
        assert pubsub.closed is True

    @pytest.mark.asyncio
    async def test_redis_transport_error_is_handled(self):
        """A transport error in get_message is logged and ends the listener
        cleanly (no exception escapes).

        ``stream_ready`` is still queued (subscribe completes before the
        first get_message call), so the queue contains exactly that frame
        and nothing else.
        """
        queue: asyncio.Queue = asyncio.Queue()

        class _Pubsub:
            async def subscribe(self, *channels):
                pass

            async def get_message(self, timeout=1.0):
                raise RuntimeError("redis connection dropped")

            async def unsubscribe(self):
                pass

            async def close(self):
                pass

        redis = MagicMock()
        redis.pubsub.return_value = _Pubsub()

        # The coroutine must complete without raising.
        await _redis_listener_coro(redis, queue, ["jobs:global"], "cid")
        # Only the legitimate stream_ready frame is present; the transport
        # error didn't produce any additional queued items.
        assert queue.qsize() == 1
        assert queue.get_nowait() == {"event": "stream_ready"}


class TestEventGeneratorWireFormat:
    """Regression tests for a real production bug: _event_generator used to
    pre-format "data: {json}\\n\\n" and yield it as a plain string.
    EventSourceResponse feeds whatever a generator yields into
    sse_starlette's ensure_bytes()/ServerSentEvent.encode(), which ALREADY
    prefixes "data: " and splits on embedded newlines - given an
    already-prefixed, already-terminated string, it wrapped the whole thing
    AGAIN, producing "data: data: {json}\\r\\ndata: \\r\\ndata: \\r\\n\\r\\n"
    on the wire. The browser's EventSource then handed a non-JSON string to
    JSON.parse(), which threw and was silently swallowed by the frontend's
    catch-and-ignore - so every stream_ready/refresh_progress/refresh_done
    frame was dropped, with no visible error anywhere. Confirmed against a
    captured HAR of the actual malformed bytes.

    These tests exercise the REAL sse_starlette encoding path (not a mock),
    since that's the only way to catch this class of bug - test_api_jobs_stream.py
    stubs out EventSourceResponse entirely and can't see it.
    """

    @pytest.mark.asyncio
    async def test_yielded_event_encodes_to_a_single_parseable_data_line(self):
        from sse_starlette.sse import ensure_bytes

        controlled: asyncio.Queue = asyncio.Queue()
        await controlled.put({"event": "stream_ready"})

        call_count = {"n": 0}

        async def _disconnected_after_one() -> bool:
            call_count["n"] += 1
            return call_count["n"] > 1

        with patch.object(
            stream_module, "_subscribe_job_stream", return_value=controlled
        ):
            request = MagicMock()
            request.is_disconnected = _disconnected_after_one

            events = [
                e async for e in _event_generator(request, job_id="abc", redis=None)
            ]

        assert len(events) == 1

        # This is exactly what EventSourceResponse.stream_response() does
        # with each yielded value before writing it to the wire.
        wire_bytes = ensure_bytes(events[0], sep="\r\n")
        wire_text = wire_bytes.decode()

        data_lines = [
            line for line in wire_text.split("\r\n") if line.startswith("data:")
        ]
        assert len(data_lines) == 1, (
            f"expected exactly one 'data:' line, got {data_lines!r} "
            f"(full frame: {wire_text!r})"
        )

        # And it round-trips through JSON exactly as the browser's
        # EventSource + JSON.parse(e.data) would consume it.
        payload = data_lines[0][len("data: ") :]
        assert json.loads(payload) == {"event": "stream_ready"}

    def test_heartbeat_encodes_as_a_comment_not_a_data_line(self):
        """The heartbeat must be a genuine SSE comment (leading ':'), not a
        'data:' line - EventSource ignores comments but a malformed 'data:
        : keepalive' line would be handed to JSON.parse() and (harmlessly,
        but wrongly) dropped as a parse failure like everything else was."""
        frame = ServerSentEvent(comment="keepalive").encode().decode()

        assert frame.startswith(": keepalive")
        assert "data:" not in frame
