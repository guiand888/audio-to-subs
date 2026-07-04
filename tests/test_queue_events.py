"""Tests for queue event publishing (pub/sub)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import fakeredis.aioredis


@pytest.mark.asyncio
async def test_publish_new_event():
    """Test that publish_new actually sends data to Redis."""
    from audio_to_subs.queue_.events import publish_new

    # Use fake Redis to capture the published message
    redis = fakeredis.aioredis.FakeRedis()

    try:
        # Set up a listener
        pubsub = redis.pubsub()
        await pubsub.subscribe("jobs:new")

        # Publish an event
        job_id = "test-job-123"
        payload = {"id": job_id, "status": "queued"}
        await publish_new(redis, job_id, payload)

        # Verify the message was published
        message = await pubsub.get_message()
        assert message is not None
        assert message["type"] == "subscribe"

        # Get the actual published message (not the subscribe response)
        message = await pubsub.get_message(timeout=1.0)
        assert message is not None
        assert message["type"] == "message"
        assert message["channel"] == b"jobs:new"

    finally:
        await pubsub.unsubscribe()
        await redis.close()


@pytest.mark.asyncio
async def test_publish_progress_event():
    """Test progress events are published to job-specific channels."""
    from audio_to_subs.queue_.events import publish_progress

    redis = fakeredis.aioredis.FakeRedis()

    try:
        pubsub = redis.pubsub()
        job_id = "test-job-456"
        await pubsub.subscribe(f"jobs:{job_id}:progress")

        payload = {"progress_percent": 50, "message": "Half done"}
        await publish_progress(redis, job_id, payload)

        # Verify subscription succeeded
        await pubsub.get_message()

        # Verify the message was published
        message = await pubsub.get_message(timeout=1.0)
        assert message is not None
        assert message["type"] == "message"

    finally:
        await pubsub.unsubscribe()
        await redis.close()
