"""
Init schema for HealthOS MVP.

Creates tenant-scoped tables:
- patients
- encounters
- tasks
- notes
- claims
- agent_logs
- audit_trail
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_init_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Upgrade schema to the initial MVP tables.
    """
    # Enable pgcrypto for gen_random_uuid() if available (Postgres 13+ commonly supports it).
    # This keeps UUID generation DB-side if you choose to use server defaults later.
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    # ---- Enum types ----
    # NOTE: create_type=False prevents SQLAlchemy from auto-creating these enum
    # types as a side effect of op.create_table() (which does NOT pass
    # checkfirst). We create them explicitly below with checkfirst=True so the
    # migration is idempotent if a previous run left some types behind.
    task_type = postgresql.ENUM(
        "ORCHESTRATE", "DOCUMENT", "RCM_AUDIT", name="tasktype", create_type=False
    )
    task_status = postgresql.ENUM(
        "QUEUED",
        "RUNNING",
        "BLOCKED",
        "SUCCEEDED",
        "FAILED",
        "CANCELLED",
        name="taskstatus",
        create_type=False,
    )
    hitl_status = postgresql.ENUM(
        "NOT_REQUIRED",
        "REQUIRED",
        "IN_REVIEW",
        "APPROVED",
        "REJECTED",
        name="hitlstatus",
        create_type=False,
    )
    priority = postgresql.ENUM(
        "LOW", "NORMAL", "HIGH", "URGENT", name="priority", create_type=False
    )
    encounter_status = postgresql.ENUM(
        "PLANNED",
        "IN_PROGRESS",
        "FINISHED",
        "CANCELLED",
        name="encounterstatus",
        create_type=False,
    )
    note_status = postgresql.ENUM(
        "DRAFT",
        "IN_REVIEW",
        "APPROVED",
        "REJECTED",
        name="notestatus",
        create_type=False,
    )
    claim_status = postgresql.ENUM(
        "DRAFT",
        "READY_TO_SUBMIT",
        "SUBMITTED",
        "ACCEPTED",
        "DENIED",
        "PAID",
        "VOIDED",
        name="claimstatus",
        create_type=False,
    )
    actor_type = postgresql.ENUM(
        "SYSTEM", "USER", "AGENT", name="actortype", create_type=False
    )

    bind = op.get_bind()
    task_type.create(bind, checkfirst=True)
    task_status.create(bind, checkfirst=True)
    hitl_status.create(bind, checkfirst=True)
    priority.create(bind, checkfirst=True)
    encounter_status.create(bind, checkfirst=True)
    note_status.create(bind, checkfirst=True)
    claim_status.create(bind, checkfirst=True)
    actor_type.create(bind, checkfirst=True)

    # ---- patients ----
    op.create_table(
        "patients",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mrn", sa.String(length=64), nullable=False),
        sa.Column("fhir_patient_id", sa.String(length=128), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=200), nullable=True),
        sa.Column(
            "patient_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.UniqueConstraint("tenant_id", "mrn", name="uq_patients_tenant_mrn"),
    )
    op.create_index("ix_patients_tenant_id", "patients", ["tenant_id"])
    op.create_index("ix_patients_fhir_patient_id", "patients", ["fhir_patient_id"])
    op.create_index(
        "ix_patients_tenant_last_name", "patients", ["tenant_id", "last_name"]
    )

    # ---- encounters ----
    op.create_table(
        "encounters",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fhir_encounter_id", sa.String(length=128), nullable=True),
        sa.Column("status", encounter_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "encounter_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name="fk_encounters_patient_id_patients"
        ),
    )
    op.create_index("ix_encounters_tenant_id", "encounters", ["tenant_id"])
    op.create_index("ix_encounters_patient_id", "encounters", ["patient_id"])
    op.create_index(
        "ix_encounters_fhir_encounter_id", "encounters", ["fhir_encounter_id"]
    )
    op.create_index(
        "ix_encounters_tenant_status", "encounters", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_encounters_tenant_patient", "encounters", ["tenant_id", "patient_id"]
    )

    # ---- tasks ----
    op.create_table(
        "tasks",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_type", task_type, nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("priority", priority, nullable=False),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "hitl_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("hitl_status", hitl_status, nullable=False),
        sa.Column("hitl_reviewer_id", sa.String(length=128), nullable=True),
        sa.Column(
            "agent_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "agent_outputs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "confidence_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "model_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("input_hash", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["patient_id"], ["patients.id"], name="fk_tasks_patient_id_patients"
        ),
        sa.ForeignKeyConstraint(
            ["encounter_id"], ["encounters.id"], name="fk_tasks_encounter_id_encounters"
        ),
    )
    op.create_index("ix_tasks_tenant_id", "tasks", ["tenant_id"])
    op.create_index("ix_tasks_task_type", "tasks", ["task_type"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_priority", "tasks", ["priority"])
    op.create_index("ix_tasks_patient_id", "tasks", ["patient_id"])
    op.create_index("ix_tasks_encounter_id", "tasks", ["encounter_id"])
    op.create_index("ix_tasks_hitl_status", "tasks", ["hitl_status"])
    op.create_index("ix_tasks_input_hash", "tasks", ["input_hash"])
    op.create_index("ix_tasks_started_at", "tasks", ["started_at"])
    op.create_index("ix_tasks_completed_at", "tasks", ["completed_at"])
    op.create_index(
        "ix_tasks_tenant_status_created", "tasks", ["tenant_id", "status", "created_at"]
    )
    op.create_index(
        "ix_tasks_tenant_type_created",
        "tasks",
        ["tenant_id", "task_type", "created_at"],
    )
    op.create_index(
        "ix_tasks_tenant_hitl", "tasks", ["tenant_id", "hitl_required", "hitl_status"]
    )

    # ---- notes ----
    op.create_table(
        "notes",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", note_status, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column(
            "soap",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "validation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "model_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fhir_documentreference_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["encounter_id"], ["encounters.id"], name="fk_notes_encounter_id_encounters"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_notes_task_id_tasks"
        ),
    )
    op.create_index("ix_notes_tenant_id", "notes", ["tenant_id"])
    op.create_index("ix_notes_encounter_id", "notes", ["encounter_id"])
    op.create_index("ix_notes_task_id", "notes", ["task_id"])
    op.create_index("ix_notes_status", "notes", ["status"])
    op.create_index(
        "ix_notes_fhir_documentreference_id", "notes", ["fhir_documentreference_id"]
    )
    op.create_index(
        "ix_notes_tenant_status_created", "notes", ["tenant_id", "status", "created_at"]
    )
    op.create_index("ix_notes_tenant_encounter", "notes", ["tenant_id", "encounter_id"])

    # ---- claims ----
    op.create_table(
        "claims",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", claim_status, nullable=False),
        sa.Column("payer_name", sa.String(length=200), nullable=True),
        sa.Column("payer_member_id", sa.String(length=128), nullable=True),
        sa.Column(
            "coding_suggestions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "payer_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "denial_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "validation_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "model_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("adjudicated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("denial_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_by", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["encounter_id"],
            ["encounters.id"],
            name="fk_claims_encounter_id_encounters",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_claims_task_id_tasks"
        ),
    )
    op.create_index("ix_claims_tenant_id", "claims", ["tenant_id"])
    op.create_index("ix_claims_encounter_id", "claims", ["encounter_id"])
    op.create_index("ix_claims_task_id", "claims", ["task_id"])
    op.create_index("ix_claims_status", "claims", ["status"])
    op.create_index(
        "ix_claims_tenant_status_created",
        "claims",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_claims_tenant_encounter", "claims", ["tenant_id", "encounter_id"]
    )

    # ---- agent_logs ----
    op.create_table(
        "agent_logs",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("agent_name", sa.String(length=100), nullable=False),
        sa.Column(
            "level",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'INFO'"),
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "model_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_agent_logs_task_id_tasks"
        ),
    )
    op.create_index("ix_agent_logs_tenant_id", "agent_logs", ["tenant_id"])
    op.create_index("ix_agent_logs_task_id", "agent_logs", ["task_id"])
    op.create_index("ix_agent_logs_agent_name", "agent_logs", ["agent_name"])
    op.create_index("ix_agent_logs_level", "agent_logs", ["level"])
    op.create_index(
        "ix_agent_logs_tenant_created", "agent_logs", ["tenant_id", "created_at"]
    )
    op.create_index(
        "ix_agent_logs_tenant_agent_created",
        "agent_logs",
        ["tenant_id", "agent_name", "created_at"],
    )

    # ---- audit_trail ---- (append-only)
    op.create_table(
        "audit_trail",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column("actor_type", actor_type, nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "event_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name="fk_audit_trail_task_id_tasks"
        ),
    )
    op.create_index("ix_audit_trail_tenant_id", "audit_trail", ["tenant_id"])
    op.create_index("ix_audit_trail_task_id", "audit_trail", ["task_id"])
    op.create_index("ix_audit_trail_actor_id", "audit_trail", ["actor_id"])
    op.create_index("ix_audit_trail_actor_type", "audit_trail", ["actor_type"])
    op.create_index("ix_audit_trail_action", "audit_trail", ["action"])
    op.create_index("ix_audit_trail_resource_type", "audit_trail", ["resource_type"])
    op.create_index("ix_audit_trail_resource_id", "audit_trail", ["resource_id"])
    op.create_index(
        "ix_audit_trail_tenant_created", "audit_trail", ["tenant_id", "created_at"]
    )
    op.create_index(
        "ix_audit_trail_tenant_resource",
        "audit_trail",
        ["tenant_id", "resource_type", "resource_id"],
    )


def downgrade() -> None:
    """
    Downgrade schema by dropping all MVP tables and enum types.
    """
    op.drop_table("audit_trail")
    op.drop_table("agent_logs")
    op.drop_table("claims")
    op.drop_table("notes")
    op.drop_table("tasks")
    op.drop_table("encounters")
    op.drop_table("patients")

    op.execute('DROP EXTENSION IF EXISTS "pgcrypto";')

    postgresql.ENUM(name="actortype").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="claimstatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="notestatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="encounterstatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="priority").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="hitlstatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="taskstatus").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="tasktype").drop(op.get_bind(), checkfirst=True)
