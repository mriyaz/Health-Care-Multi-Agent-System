"""
OAuth2-style password login + JWT access tokens + rotating refresh tokens (P0#13).

- ``POST /auth/token`` — form ``username`` / ``password`` (OAuth2 password grant shape).
- ``POST /auth/refresh`` — JSON body ``{ "refresh_token": "..." }``.
"""

from __future__ import annotations

import secrets
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import passwords, tokens
from api.auth.deps import get_current_active_principal
from api.auth.principal import AuthPrincipal
from api.auth.refresh_store import (
    delete_refresh_binding,
    get_refresh_binding,
    refresh_ttl_seconds,
    store_refresh_binding,
)
from api.auth.tokens import decode_refresh_payload
from api.deps import get_db
from db.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token lifetime in seconds.")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20)


@router.post("/token", response_model=TokenResponse)
async def issue_tokens(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    settings = request.app.state.settings
    redis = request.app.state.redis

    result = await db.execute(select(User).where(User.username == form.username))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if not passwords.verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    access, expires_in = tokens.create_access_token(
        settings,
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    jti = secrets.token_urlsafe(32)
    family_id = secrets.token_urlsafe(16)
    refresh = tokens.create_refresh_token(
        settings,
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        jti=jti,
        family_id=family_id,
    )
    ttl = refresh_ttl_seconds(settings)
    await store_refresh_binding(
        redis,
        jti=jti,
        user_id=str(user.id),
        family_id=family_id,
        ttl_seconds=ttl,
    )
    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=expires_in,
    )


@router.post("/refresh", response_model=TokenResponse)
async def rotate_refresh_token(
    request: Request,
    body: RefreshRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    settings = request.app.state.settings
    redis = request.app.state.redis

    try:
        payload = decode_refresh_payload(settings, body.refresh_token)
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from None

    jti = str(payload["jti"])
    fam = str(payload["fam"])
    binding = await get_refresh_binding(redis, jti)
    if binding is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked, expired, or already rotated",
        )
    if binding.get("fam") != fam or binding.get("sub") != payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token mismatch",
        )

    await delete_refresh_binding(redis, jti)

    try:
        uid = UUID(str(payload["sub"]))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from exc

    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive or unknown")

    access, expires_in = tokens.create_access_token(
        settings,
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
    )
    new_jti = secrets.token_urlsafe(32)
    new_refresh = tokens.create_refresh_token(
        settings,
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        jti=new_jti,
        family_id=fam,
    )
    ttl = refresh_ttl_seconds(settings)
    await store_refresh_binding(
        redis,
        jti=new_jti,
        user_id=str(user.id),
        family_id=fam,
        ttl_seconds=ttl,
    )
    return TokenResponse(
        access_token=access,
        refresh_token=new_refresh,
        expires_in=expires_in,
    )


@router.get("/me", response_model=AuthPrincipal)
async def who_am_i(
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
) -> AuthPrincipal:
    """Return the authenticated user's id, tenant, and RBAC role (from DB)."""
    return principal
