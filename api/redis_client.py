"""
Async Redis connectivity for the FastAPI app.

Celery uses its own synchronous Redis connections in the worker process; this
module is for request-path async I/O (sessions, pub/sub, health checks).
"""

from __future__ import annotations

from redis.asyncio import Redis


def create_async_redis(url: str) -> Redis:
    """
    Build a Redis client with decoded string responses for JSON.session and pub/sub.
    """
    return Redis.from_url(url, decode_responses=True, encoding="utf-8")


async def ping_redis(redis: Redis) -> bool:
    try:
        return bool(await redis.ping())
    except Exception:
        return False
