"""
Extend tasktype enum for Section C orchestrator routing (PRD task_type labels).

Adds: CODE_AUDIT, PRIOR_AUTH, ENGAGE, TRIAGE (RCM_AUDIT retained as alias in app layer).
"""

from __future__ import annotations

from alembic import op

revision = "0003_extend_tasktype"
down_revision = "0002_users_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 9.1+ allows ADD VALUE inside a transaction; IF NOT EXISTS needs PG15+.
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'CODE_AUDIT'")
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'PRIOR_AUTH'")
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'ENGAGE'")
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'TRIAGE'")


def downgrade() -> None:
    """
    Postgres enums cannot safely drop labels without recreating the type.

    Downgrade is intentionally a no-op to avoid breaking existing task rows.
    """
    pass
