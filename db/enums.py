"""
db/enums.py

Domain enums for HealthOS persistence.

Enums are used by SQLAlchemy models and constrain critical state transitions
for tasks, encounters, notes, and claims.
"""

from __future__ import annotations

import enum


class TaskType(str, enum.Enum):
    """
    Types of orchestrated work the platform can run.
    """

    ORCHESTRATE = "ORCHESTRATE"
    DOCUMENT = "DOCUMENT"
    RCM_AUDIT = "RCM_AUDIT"
    #: Checklist / PRD alias for revenue-cycle coding audit (same downstream agent as RCM_AUDIT).
    CODE_AUDIT = "CODE_AUDIT"
    PRIOR_AUTH = "PRIOR_AUTH"
    ENGAGE = "ENGAGE"
    TRIAGE = "TRIAGE"


class TaskStatus(str, enum.Enum):
    """
    High-level lifecycle for async tasks.
    """

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"  # waiting on HITL or external dependency
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class HITLStatus(str, enum.Enum):
    """
    Human-in-the-loop (review/approval) status.
    """

    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Priority(str, enum.Enum):
    """
    Task priority for queue ordering and escalation.
    """

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class EncounterStatus(str, enum.Enum):
    """
    Encounter status aligned with common EHR/FHIR patterns.
    """

    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class NoteStatus(str, enum.Enum):
    """
    Clinical note workflow: draft -> review -> approved.
    """

    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimStatus(str, enum.Enum):
    """
    Simplified claims lifecycle for MVP RCM workflows.
    """

    DRAFT = "DRAFT"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ActorType(str, enum.Enum):
    """
    Audit actor classification.
    """

    SYSTEM = "SYSTEM"
    USER = "USER"
    AGENT = "AGENT"


class UserRole(str, enum.Enum):
    """
    API RBAC roles (checklist Section K — admin, clinician, biller, reviewer).

    Values match Postgres enum ``userrole`` (Alembic ``0002_users_auth``).
    """

    ADMIN = "ADMIN"
    CLINICIAN = "CLINICIAN"
    BILLER = "BILLER"
    REVIEWER = "REVIEWER"
