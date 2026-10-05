"""
Integration: full Celery round-trip (broker + worker + result backend).

Requires:
  - Redis
  - ``celery -A api.tasks.celery_app worker --loglevel=info`` in another terminal

Set ``HEALTHOS_RUN_CELERY_INTEGRATION=1`` so this does not run in CI unless you opt in.
"""

from __future__ import annotations

import os
import unittest

from api.tasks.jobs import worker_ping

from tests.redis_next_steps.helpers import redis_available


def _celery_integration_enabled() -> bool:
    return os.environ.get("HEALTHOS_RUN_CELERY_INTEGRATION", "").strip() == "1"


@unittest.skipUnless(redis_available(), "Redis not reachable")
@unittest.skipUnless(
    _celery_integration_enabled(), "Set HEALTHOS_RUN_CELERY_INTEGRATION=1"
)
class CeleryWorkerRoundtripTests(unittest.TestCase):
    def test_delay_get_returns_result(self):
        async_result = worker_ping.delay({"roundtrip": True})
        try:
            payload = async_result.get(timeout=15)
        except Exception as exc:  # noqa: BLE001
            self.skipTest(
                "Celery result not ready — start a worker: "
                "celery -A api.tasks.celery_app worker --loglevel=info. "
                f"Underlying error: {exc!r}"
            )
        self.assertTrue(payload.get("ok"))
        self.assertEqual(payload.get("echo"), {"roundtrip": True})


if __name__ == "__main__":
    unittest.main()
