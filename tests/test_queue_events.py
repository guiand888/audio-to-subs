"""Tests for queue event publishing (pub/sub) and SSE observer registration."""

import asyncio
import json

import fakeredis.aioredis
import pytest


@pytest.mark.asyncio
async def test_publish_new_event():
    """Test that publish_new actually sends data to Redis and calls observers."""
    from audio_to_subs.queue_.events import publish_new

    redis = fakeredis.aioredis.FakeRedis()

    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe("jobs:new", "jobs:global")

        job_id = "test-job-123"
        await publish_new(redis, job_id)

        # Skip subscription confirmation messages
        await pubsub.get_message()
        await pubsub.get_message()

        # Get the actual published messages from the channels
        message = await asyncio.wait_for(pubsub.get_message(timeout=1.0), timeout=2.0)
        assert message is not None
        assert message["type"] == "message"

    finally:
        await pubsub.unsubscribe()
        await redis.aclose()


@pytest.mark.asyncio
async def test_publish_progress_event():
    """Test progress events are published to job-specific and global channels."""
    from audio_to_subs.queue_.events import publish_progress

    redis = fakeredis.aioredis.FakeRedis()

    try:
        pubsub = redis.pubsub()
        job_id = "test-job-456"
        await pubsub.subscribe(f"jobs:progress:{job_id}", "jobs:global")

        # Skip subscription confirmations
        await pubsub.get_message()
        await pubsub.get_message()

        await publish_progress(redis, job_id, 50, "processing", "Half done")

        # Get message from job-specific channel
        message = await asyncio.wait_for(pubsub.get_message(timeout=1.0), timeout=2.0)
        assert message is not None
        assert message["type"] == "message"

    finally:
        await pubsub.unsubscribe()
        await redis.aclose()


@pytest.mark.asyncio
async def test_new_event_delivered_once_to_global_subscriber():
    """Regression (M5.8 #3): API-originated ``new`` events used to be
    delivered twice to each SSE client — once via Redis ``_publish`` and once
    via the in-process observer's own Redis publish to the same channel.
    After removing the observer path, a single ``publish_new`` must produce
    exactly one ``event: new`` on ``jobs:global``.
    """
    from audio_to_subs.queue_.events import publish_new

    redis = fakeredis.aioredis.FakeRedis()
    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe("jobs:global")
        await pubsub.get_message()  # skip subscription confirmation

        await publish_new(redis, "once-job-new")

        seen = []
        for _ in range(10):
            msg = await asyncio.wait_for(pubsub.get_message(timeout=0.3), timeout=1.0)
            if msg and msg.get("type") == "message":
                data = json.loads(msg["data"])
                if data.get("event") == "new":
                    seen.append(data)

        assert len(seen) == 1
        assert seen[0]["job_id"] == "once-job-new"
    finally:
        await pubsub.unsubscribe()
        await redis.aclose()


@pytest.mark.asyncio
async def test_cancel_event_delivered_once_to_global_subscriber():
    """Regression (M5.8 #3): same as the ``new`` case, for API-originated
    ``cancel`` events — exactly one ``event: cancel`` on ``jobs:global``.
    """
    from audio_to_subs.queue_.events import publish_cancel

    redis = fakeredis.aioredis.FakeRedis()
    try:
        pubsub = redis.pubsub()
        await pubsub.subscribe("jobs:global")
        await pubsub.get_message()  # skip subscription confirmation

        await publish_cancel(redis, "once-job-cancel")

        seen = []
        for _ in range(10):
            msg = await asyncio.wait_for(pubsub.get_message(timeout=0.3), timeout=1.0)
            if msg and msg.get("type") == "message":
                data = json.loads(msg["data"])
                if data.get("event") == "cancel":
                    seen.append(data)

        assert len(seen) == 1
        assert seen[0]["job_id"] == "once-job-cancel"
    finally:
        await pubsub.unsubscribe()
        await redis.aclose()


@pytest.mark.asyncio
async def test_multi_worker_sse_event_delivery():
    """Test that SSE events propagate via Redis across workers.

    This test simulates two workers using a shared Redis instance:
    one publishes an event, another receives it via Redis subscription.
    """
    import json

    from audio_to_subs.queue_.events import publish_progress

    # Shared Redis instance (both "workers" use the same instance)
    redis = fakeredis.aioredis.FakeRedis()

    try:
        job_id = "test-job-multiworker"

        # Background task: listen to Redis (simulating SSE generator's Redis listener on worker 2)
        received_events = []

        async def redis_listener():
            """Simulate the Redis listener in _event_generator."""
            pubsub = redis.pubsub()
            await pubsub.subscribe(f"jobs:progress:{job_id}")
            await pubsub.get_message()  # Skip subscription confirmation

            try:
                for _ in range(2):  # Expect 2 events
                    message = await asyncio.wait_for(
                        pubsub.get_message(timeout=0.5), timeout=2.0
                    )
                    if message and message.get("type") == "message":
                        data = json.loads(message["data"])
                        received_events.append(data)
            finally:
                await pubsub.unsubscribe()
                await pubsub.aclose()

        # Start the listener (simulating worker 2 listening)
        listener_task = asyncio.create_task(redis_listener())

        # Small delay to ensure listener is subscribed
        await asyncio.sleep(0.1)

        # Worker 1: publish events via Redis
        await publish_progress(redis, job_id, 25, "stage1", "Starting")
        await publish_progress(redis, job_id, 75, "stage2", "Processing")

        # Wait for listener to receive events
        await asyncio.wait_for(listener_task, timeout=3.0)

        # Verify events were received via Redis
        assert len(received_events) >= 2
        assert received_events[0]["percent"] == 25
        assert received_events[1]["percent"] == 75

    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_publish_progress_includes_step_fields():
    """M5.8: progress payload must carry step_index/step_total."""
    from audio_to_subs.queue_.events import publish_progress

    redis = fakeredis.aioredis.FakeRedis()
    try:
        pubsub = redis.pubsub()
        job_id = "step-job"
        await pubsub.subscribe(f"jobs:progress:{job_id}", "jobs:global")
        await pubsub.get_message()
        await pubsub.get_message()

        await publish_progress(
            redis, job_id, 42, "extract", "Extracting", step_index=1, step_total=4
        )

        # job-specific channel
        msg = await asyncio.wait_for(pubsub.get_message(timeout=1.0), timeout=2.0)
        assert msg is not None
        payload = json.loads(msg["data"])
        assert payload["step_index"] == 1
        assert payload["step_total"] == 4
        assert payload["stage"] == "extract"
    finally:
        await pubsub.unsubscribe()
        await redis.aclose()
