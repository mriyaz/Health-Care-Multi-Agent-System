"""
db/base.py

SQLAlchemy declarative base, naming conventions, and reusable mixins.

We use:
- UUID primary keys for global uniqueness
- timezone-aware timestamps
- tenant_id on every tenant-scoped table for multi-tenant isolation from day one
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """
    Return a timezone-aware UTC timestamp.

    We keep this in one place so models/migrations stay consistent.
    """
    return datetime.now(timezone.utc)


NAMING_CONVENTION = {
    # These conventions help Alembic autogenerate stable constraint names.
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """
    Declarative base class for all models.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TenantScopedMixin:
    """
    Adds tenant_id to enforce tenant isolation at the database layer.
    """

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, index=True
    )


class TimestampMixin:
    """
    Adds created_at and updated_at timestamps.

    updated_at should be updated by application code on updates; later you can
    enforce it via DB triggers if desired.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ActorMixin:
    """
    Adds created_by/updated_by for human/system attribution.

    For MVP, these are strings; later they can become FKs to a users table.
    """

    created_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
