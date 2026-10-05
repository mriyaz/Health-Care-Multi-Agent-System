"""
Pytest bootstrap: keep LangGraph checkpoints in-memory so CI does not require Postgres.

Developers can override with ``HEALTHOS_ORCHESTRATOR_CHECKPOINTER=postgres`` for integration runs.
"""

from __future__ import annotations

import os

# Test-only placeholders so imports can construct Settings without a local .env.
# They are not credentials for any deployed system.
os.environ.setdefault("HEALTHOS_ORCHESTRATOR_CHECKPOINTER", "memory")
os.environ.setdefault("SESSION_SECRET_KEY", "test-only-session-secret-value-32ch")
os.environ.setdefault("JWT_SECRET_KEY", "test-only-jwt-secret-value-32chars!")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://healthos:local_dev_only_change_me@localhost:5432/healthos",
)
