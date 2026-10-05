"""Integration: publish_agent_event + asyncio subscriber on the global channel."""

from __future__ import annotations

import json
import unittest

from redis.asyncio import Redis

from api.events.agent_events import CHANNEL_AGENT_EVENTS_ALL, publish_agent_event

from tests.redis_next_steps.helpers import redis_available, redis_url


@unittest.skipUnless(redis_available(), "Redis not reachable (start Docker / redis)")
class AgentEventsPubSubTests(unittest.IsolatedAsyncioTestCase):
    async def test_global_channel_receives_envelope(self):
        redis = Redis.from_url(redis_url(), decode_responses=True)
        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(CHANNEL_AGENT_EVENTS_ALL)
            await pubsub.get_message(ignore_subscribe_messages=True, timeout=2.0)

            receivers = await publish_agent_event(
                redis,
                event_type="tests.next_steps.smoke",
                data={"task_id": "test-123"},
                tenant_id="tenant-a",
            )
            self.assertIsInstance(receivers, int)

            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=3.0)
            self.assertIsNotNone(msg, "no pub/sub message received")
            self.assertEqual(msg.get("type"), "message")
            envelope = json.loads(msg["data"])
            self.assertEqual(envelope["event_type"], "tests.next_steps.smoke")
            self.assertEqual(envelope["tenant_id"], "tenant-a")
            self.assertEqual(envelope["data"]["task_id"], "test-123")
        finally:
            await pubsub.unsubscribe(CHANNEL_AGENT_EVENTS_ALL)
            await pubsub.aclose()
            await redis.aclose()


if __name__ == "__main__":
    unittest.main()
