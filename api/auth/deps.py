"""
Authentication / RBAC dependencies for FastAPI routes.

Uses OAuth2 bearer tokens (JWT access). OpenAPI ``Authorize`` uses ``POST /auth/token``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import AuthPrincipal
from api.auth.tokens import decode_access_principal
from api.deps import get_db
from api.settings import Settings
from db.enums import UserRole
from db.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_current_principal(
    settings: Annotated[Settings, Depends(get_app_settings)],
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthPrincipal:
    """
    Validate bearer JWT, load the user, and return principal with **current** role from DB.
    """
    try:
        payload = decode_access_principal(settings, token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token expired",
        ) from None
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        ) from exc

    uid_str = payload.get("sub")
    tid_str = payload.get("tid")
    if not uid_str or not tid_str:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    try:
        user_uuid = UUID(uid_str)
        token_tenant = UUID(tid_str)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token claims") from exc

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User inactive or unknown")
    if user.tenant_id != token_tenant:
        raise HTTPException(status_code=401, detail="Tenant mismatch")

    return AuthPrincipal(user_id=user.id, tenant_id=user.tenant_id, role=user.role)


async def get_current_active_principal(
    principal: Annotated[AuthPrincipal, Depends(get_current_principal)],
) -> AuthPrincipal:
    return principal


def require_roles(*allowed: UserRole):
    """
    Dependency factory: allow only listed RBAC roles (OR).
    """

    allowed_set = set(allowed)

    async def _req(
        p: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    ) -> AuthPrincipal:
        if p.role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this operation",
            )
        return p

    return _req
