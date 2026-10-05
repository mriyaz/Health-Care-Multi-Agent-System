"""Integration: enqueue message to Celery broker (Redis) without a worker."""

from __future__ import annotations

import unittest

from api.tasks.jobs import worker_ping

from tests.redis_next_steps.helpers import redis_available


@unittest.skipUnless(redis_available(), "Redis not reachable")
class CeleryBrokerEnqueueTests(unittest.TestCase):
    def test_delay_returns_task_id(self):
        """
        ``delay`` serialises the task to the broker. The API returns immediately with an id.

        If no worker is running, the message waits in the queue — this test still passes.
        """
        async_result = worker_ping.delay({"from": "broker_enqueue_test"})
        self.assertIsNotNone(async_result.id)


if __name__ == "__main__":
    unittest.main()
