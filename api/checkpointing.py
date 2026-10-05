"""LangGraph Postgres checkpointer wiring (Section C — checklist #29)."""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from api.settings import Settings


async def create_checkpoint_pool(settings: Settings) -> AsyncConnectionPool:
    """
    Async connection pool for ``AsyncPostgresSaver``.

    Uses psycopg3 (sync URL + libpq), distinct from SQLAlchemy's asyncpg URL.
    """
    pool = AsyncConnectionPool(
        conninfo=settings.get_checkpoint_conninfo(),
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        open=False,
        max_size=10,
    )
    await pool.open()
    return pool


async def setup_async_postgres_checkpointer(
    pool: AsyncConnectionPool,
) -> AsyncPostgresSaver:
    saver = AsyncPostgresSaver(pool)
    await saver.setup()
    return saver
