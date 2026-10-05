"""
Redis-backed refresh token handles (rotation).

Each refresh JWT carries a unique ``jti``. We store ``{sub, fam}`` under that jti until the
token is consumed by ``POST /auth/refresh``, then we delete it and bind a new jti — classic
refresh rotation: presenting an old refresh token after rotation fails because Redis no longer
has that jti.
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from api.settings import Settings

REFRESH_KEY_PREFIX = "healthos:auth:rt:"


async def store_refresh_binding(
    redis: Redis,
    *,
    jti: str,
    user_id: str,
    family_id: str,
    ttl_seconds: int,
) -> None:
    payload = json.dumps({"sub": user_id, "fam": family_id})
    await redis.setex(f"{REFRESH_KEY_PREFIX}{jti}", ttl_seconds, payload)


async def get_refresh_binding(redis: Redis, jti: str) -> dict[str, Any] | None:
    raw = await redis.get(f"{REFRESH_KEY_PREFIX}{jti}")
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


async def delete_refresh_binding(redis: Redis, jti: str) -> None:
    await redis.delete(f"{REFRESH_KEY_PREFIX}{jti}")


def refresh_ttl_seconds(settings: Settings) -> int:
    return int(settings.jwt_refresh_expire_days * 24 * 60 * 60)
