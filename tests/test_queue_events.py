"""Tests for queue event publishing (pub/sub) and SSE observer registration."""

import asyncio

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
async def test_observer_registration():
    """Test that SSE observers can be registered with the events module."""
    # Clear any previous observers by importing fresh
    import importlib

    import audio_to_subs.queue_.events as events_module

    importlib.reload(events_module)

    from audio_to_subs.queue_.events import (
        register_global_stream_observer,
        register_job_stream_observer,
    )

    # Track calls to observers
    job_events = []
    global_events = []

    async def job_observer(job_id: str, event_data: dict) -> None:
        job_events.append((job_id, event_data))

    async def global_observer(event_data: dict) -> None:
        global_events.append(event_data)

    # Register observers
    register_job_stream_observer(job_observer)
    register_global_stream_observer(global_observer)

    # Create a new Redis and publish an event
    redis = fakeredis.aioredis.FakeRedis()
    try:
        from audio_to_subs.queue_.events import publish_new

        job_id = "test-job-789"
        await publish_new(redis, job_id)

        # Give async callbacks time to execute
        await asyncio.sleep(0.1)

        # Verify observers were called
        assert len(job_events) > 0
        assert job_events[0][0] == job_id
        assert job_events[0][1]["event"] == "new"

        assert len(global_events) > 0
        assert global_events[0]["job_id"] == job_id
        assert global_events[0]["event"] == "new"

    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_sse_observer_single_worker():
    """Test SSE observer callbacks work in single-worker scenario."""
    # Clear any previous subscribers
    from audio_to_subs.api.routes import stream

    stream._job_subscribers.clear()
    stream._global_subscribers.clear()

    from audio_to_subs.api.routes.stream import (
        _subscribe_job_stream,
        publish_to_job_stream,
    )

    # Simulate a client subscribing to a job stream
    job_id = "test-job-single"
    queue = _subscribe_job_stream(job_id, "client-1")

    # Publish an event (this would normally come from events.py observer)
    await publish_to_job_stream(job_id, {"event": "progress", "percent": 50})

    # Verify event is in queue
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event["event"] == "progress"
    assert event["percent"] == 50


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
