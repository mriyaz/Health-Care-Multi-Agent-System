"""
HTTP → Celery pattern: a **minimal** FastAPI app (not the production ``api.main``).

Production will attach a similar route to the real app: validate auth, enqueue, return
``task_id`` for polling or webhooks.
"""

from __future__ import annotations

import unittest

from fastapi import Body, FastAPI
from starlette.testclient import TestClient

from api.tasks.jobs import worker_ping

from tests.redis_next_steps.helpers import redis_available


def _mini_enqueue_app() -> FastAPI:
    app = FastAPI()

    @app.post("/dev/worker-ping")
    def enqueue(body: dict = Body(default_factory=dict)) -> dict:
        async_result = worker_ping.delay(body or {})
        return {"task_id": async_result.id}

    return app


@unittest.skipUnless(redis_available(), "Redis not reachable")
class EnqueueHttpMiniAppTests(unittest.TestCase):
    def test_post_returns_task_id(self):
        client = TestClient(_mini_enqueue_app())
        response = client.post("/dev/worker-ping", json={"source": "mini_app"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIn("task_id", body)
        self.assertTrue(str(body["task_id"]))


if __name__ == "__main__":
    unittest.main()
