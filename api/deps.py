"""
FastAPI dependencies shared across routers (database session, etc.).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an AsyncSession from the app's shared session factory (see ``api.main`` lifespan).
    """
    factory = request.app.state.session_factory
    async with factory() as session:
        yield session
