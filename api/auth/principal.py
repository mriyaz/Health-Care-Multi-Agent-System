"""
Claims extracted from a validated access JWT.

Kept separate from ORM ``User`` so request handlers do not need the DB for authorization.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from db.enums import UserRole


class AuthPrincipal(BaseModel):
    """
    Identity carried on each authenticated request (from bearer access token).
    """

    user_id: UUID
    tenant_id: UUID
    role: UserRole = Field(..., description="RBAC role from UserRole enum.")
