"""Create and verify JWT access / refresh tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt

from api.settings import Settings
from db.enums import UserRole

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    settings: Settings,
    *,
    user_id: UUID,
    tenant_id: UUID,
    role: UserRole,
) -> tuple[str, int]:
    """
    Return (jwt_string, expires_in_seconds).
    """
    expire_delta = timedelta(minutes=settings.jwt_access_expire_minutes)
    exp = _utc_now() + expire_delta
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role.value,
        "typ": TOKEN_TYPE_ACCESS,
        "exp": exp,
        "iat": _utc_now(),
    }
    token = jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )
    return token, int(expire_delta.total_seconds())


def create_refresh_token(
    settings: Settings,
    *,
    user_id: UUID,
    tenant_id: UUID,
    role: UserRole,
    jti: str,
    family_id: str,
) -> str:
    expire = _utc_now() + timedelta(days=settings.jwt_refresh_expire_days)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "role": role.value,
        "typ": TOKEN_TYPE_REFRESH,
        "jti": jti,
        "fam": family_id,
        "exp": expire,
        "iat": _utc_now(),
    }
    return jwt.encode(
        payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_token(settings: Settings, token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )


def decode_access_principal(settings: Settings, token: str) -> dict[str, Any]:
    payload = decode_token(settings, token)
    if payload.get("typ") != TOKEN_TYPE_ACCESS:
        raise jwt.InvalidTokenError("Not an access token")
    return payload


def decode_refresh_payload(settings: Settings, token: str) -> dict[str, Any]:
    payload = decode_token(settings, token)
    if payload.get("typ") != TOKEN_TYPE_REFRESH:
        raise jwt.InvalidTokenError("Not a refresh token")
    for key in ("jti", "fam"):
        if not payload.get(key):
            raise jwt.InvalidTokenError(f"Missing {key}")
    return payload


def parse_role(value: object) -> UserRole:
    if isinstance(value, UserRole):
        return value
    if isinstance(value, str):
        return UserRole(value.upper())
    raise ValueError("Invalid role")
