"""Unit test: Celery task runs in-process via ``.run()`` (no broker, no worker)."""

from __future__ import annotations

import unittest

from api.tasks.jobs import worker_ping


class WorkerPingUnitTests(unittest.TestCase):
    def test_run_returns_echo(self):
        """``.run()`` is the synchronous execution path Celery uses inside the worker."""
        out = worker_ping.run({"phase": "unit"})
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("echo"), {"phase": "unit"})

    def test_run_accepts_none(self):
        out = worker_ping.run(None)
        self.assertEqual(out.get("echo"), {})


if __name__ == "__main__":
    unittest.main()
