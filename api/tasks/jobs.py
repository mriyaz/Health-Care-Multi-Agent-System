"""
Registered Celery tasks. Keep tasks idempotent when possible.

Long-running orchestration belongs here as ``.delay()`` / ``apply_async()`` callables invoked
from FastAPI endpoints once task P0 endpoints exist.
"""

from __future__ import annotations

from api.tasks.celery_app import celery_app


@celery_app.task(name="healthos.worker_ping")
def worker_ping(payload: dict | None = None) -> dict:
    """Health check proving the broker, backend, and worker process are wired."""
    return {"ok": True, "echo": payload or {}}
