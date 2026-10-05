"""
Shared helpers for Redis / Celery integration examples under ``tests/redis_next_steps``.

These are not production utilities — they only decide whether optional integration
checks should run on a developer machine.
"""

from __future__ import annotations

import os

import redis as redis_sync


def redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0").strip()


def redis_available() -> bool:
    """
    Return True if a synchronous PING against ``REDIS_URL`` succeeds.

    Used to skip tests when Docker (or local Redis) is not running.
    """
    try:
        client = redis_sync.Redis.from_url(redis_url(), socket_connect_timeout=1.0)
        client.ping()
        client.close()
        return True
    except Exception:
        return False
