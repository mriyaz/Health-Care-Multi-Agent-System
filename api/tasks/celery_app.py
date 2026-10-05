"""
Celery application: Redis broker + result backend.

Run a worker locally (from repo root, venv activated):

    celery -A api.tasks.celery_app worker --loglevel=info
"""

from __future__ import annotations

from celery import Celery

from api.settings import Settings

_settings = Settings()

celery_app = Celery(
    "healthos",
    broker=_settings.resolved_celery_broker_url,
    backend=_settings.resolved_celery_result_backend,
    include=["api.tasks.jobs"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)
