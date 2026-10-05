"""
Clinician & admin UI JSON helpers (Section J — checklist #99–#106).

Backs static pages under ``/ui/`` (SOAP review, admin dashboard, HITL queue, RCM review, etc.).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import require_roles
from api.auth.principal import AuthPrincipal
from api.deps import get_db
from api.fhir.deps import get_encounter_handler, get_patient_handler
from api.fhir.handlers.encounter import EncounterFhirHandler
from api.fhir.handlers.patient import PatientFhirHandler
from api.redis_client import ping_redis
from api.vectorstore.client import ping_weaviate
from db.base import utc_now
from db.enums import ActorType, ClaimStatus, Priority, TaskStatus, TaskType, UserRole
from db.models.audit_trail import AuditTrail
from db.models.claim import Claim
from db.models.encounter import Encounter
from db.models.patient import Patient
from db.models.task import Task
from db.models.user import User

router = APIRouter(prefix="/ui", tags=["ui"])

_clinician_roles = require_roles(
    UserRole.ADMIN,
    UserRole.CLINICIAN,
    UserRole.REVIEWER,
)

_biller_roles = require_roles(
    UserRole.ADMIN,
    UserRole.BILLER,
    UserRole.REVIEWER,
)

_admin_roles = require_roles(UserRole.ADMIN)

_DEMO_SAMPLE_COUNT = 5
_TENANT_CONFIG_PREFIX = "healthos:tenant_config:"
_PRIOR_AUTH_PREFIX = "healthos:prior_auth_board:"

_DEMO_TRANSCRIPTS: dict[str, str] = {
    "healthos-sample-encounter-001": """Chief complaint: Hypertension follow-up.

Patient reports home BP readings averaging 132–138/82–86 mmHg over the past two weeks. Denies headache, chest pain, shortness of breath, or vision changes. Taking lisinopril 10 mg daily with good adherence; no missed doses.

Vitals today: BP 128/78, HR 72, weight 154 lb (stable). Exam: alert, no acute distress; lungs clear; heart regular rate and rhythm; no peripheral edema.

Assessment: Essential hypertension, at goal on current therapy.

Plan: Continue lisinopril 10 mg daily. Reinforce low-sodium diet and regular exercise. Return in 3 months or sooner if symptomatic.""",
    "healthos-sample-encounter-002": """Chief complaint: Type 2 diabetes medication review.

Patient reports improved home glucose readings, averaging 130–145 mg/dL fasting. Denies polyuria, polydipsia, or vision changes. Taking metformin 1000 mg BID; reports good adherence.

Vitals today: BP 124/76, HR 68, weight 198 lb (down 2 lb since last visit). Exam: alert; feet without ulcers, monofilament intact bilaterally.

Assessment: Type 2 diabetes mellitus, reasonably controlled on metformin.

Plan: Continue metformin 1000 mg BID. Repeat HbA1c in 3 months. Reinforce diet and exercise. Return in 3 months or sooner if symptomatic hyperglycemia.""",
    "healthos-sample-encounter-003": """Chief complaint: Asthma symptom review.

Patient reports increased wheezing and chest tightness with exertion over the past 10 days, especially at night. Uses albuterol rescue inhaler 3–4 times per week. Denies fever or purulent sputum.

Vitals today: BP 118/74, HR 78, SpO2 98% on room air. Exam: mild expiratory wheeze bilaterally; no accessory muscle use; speaking in full sentences.

Assessment: Asthma, partially controlled; possible trigger exposure (seasonal allergens).

Plan: Continue daily low-dose ICS; add short course of oral corticosteroids if no improvement in 48 hours. Review inhaler technique. Return in 4 weeks or sooner if worsening dyspnea.""",
    "healthos-sample-encounter-004": """Chief complaint: Lower back pain assessment.

Patient describes 2-week history of aching low back pain after lifting boxes at work. Pain radiates to the left buttock but not below the knee. Worse with bending; improved with rest and NSAIDs. Denies bowel or bladder changes, saddle anesthesia, or fever.

Vitals today: BP 130/82, HR 70. Exam: tenderness over left paraspinal lumbar region; negative straight-leg raise bilaterally; normal gait; neurologic exam intact in lower extremities.

Assessment: Acute mechanical low back pain without red-flag features.

Plan: Continue NSAIDs as needed, activity modification, gentle stretching. Physical therapy referral if not improved in 2 weeks. Return sooner for new neurologic symptoms or incontinence.""",
    "healthos-sample-encounter-005": """Chief complaint: Heart failure follow-up.

Patient reports mild ankle swelling by evening and occasional dyspnea climbing one flight of stairs. Weighs self daily; up 3 lb over baseline this week. Taking furosemide 40 mg daily and carvedilol 12.5 mg BID with good adherence. Denies chest pain or orthopnea at rest.

Vitals today: BP 108/68, HR 64, weight 176 lb. Exam: 1+ pitting edema ankles; JVP not elevated; lungs with faint bibasilar crackles; no wheeze.

Assessment: Heart failure, mildly decompensated; likely fluid retention.

Plan: Increase furosemide to 40 mg BID for 5 days, then reassess weight. Continue carvedilol. Low-sodium diet counseling. Labs: BMP in 1 week. Call if weight gain >2 lb in 24 hours or worsening shortness of breath.""",
}

_DEMO_PRIOR_AUTH_CARDS = [
    {
        "id": "pa-demo-001",
        "patient_name": "Jane Sample",
        "procedure": "MRI lumbar spine (72148)",
        "payer": "UHC",
        "column": "pending",
        "submitted_at": None,
    },
    {
        "id": "pa-demo-002",
        "patient_name": "John Sample",
        "procedure": "Knee arthroscopy (29881)",
        "payer": "Aetna",
        "column": "submitted",
        "submitted_at": "2026-03-01T10:00:00Z",
    },
    {
        "id": "pa-demo-003",
        "patient_name": "Alex Sample",
        "procedure": "PET scan (78815)",
        "payer": "BCBS",
        "column": "approved",
        "submitted_at": "2026-02-20T14:30:00Z",
    },
]


class EncounterOption(BaseModel):
    encounter_id: UUID
    fhir_encounter_id: str | None
    patient_name: str
    status: str
    demo_transcript: str | None = None


class DemoBootstrapItem(BaseModel):
    internal_patient_id: UUID
    internal_encounter_id: UUID
    fhir_patient_id: str
    fhir_encounter_id: str


class DemoBootstrapResponse(BaseModel):
    synced: list[DemoBootstrapItem]


class DashboardSummary(BaseModel):
    tenant_id: UUID
    task_counts_by_status: dict[str, int]
    task_counts_by_type: dict[str, int]
    hitl_pending_count: int
    agents: dict[str, bool]
    recent_tasks: list[dict[str, Any]]


class HitlQueueItem(BaseModel):
    task_id: UUID
    task_type: TaskType
    priority: Priority
    status: TaskStatus
    encounter_id: UUID | None
    patient_id: UUID | None
    hitl_required: bool
    confidence_scores: dict[str, Any]
    agent_outputs: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AuditTrailItem(BaseModel):
    id: UUID
    task_id: UUID | None
    actor_id: str | None
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None
    event_metadata: dict[str, Any]
    created_at: datetime


class RcmReviewBody(BaseModel):
    approved: bool = True
    override_icd10: str | None = None
    override_cpt: str | None = None
    reviewer_notes: str | None = None


class TenantConfigBody(BaseModel):
    display_name: str | None = None
    llm_tier: str = Field("dev", pattern="^(dev|production|demo)$")


class PriorAuthMoveBody(BaseModel):
    column: str = Field(..., pattern="^(pending|submitted|approved|denied|appealing)$")


def _prio_rank():
    return case(
        (Task.priority == Priority.URGENT, 0),
        (Task.priority == Priority.HIGH, 1),
        (Task.priority == Priority.NORMAL, 2),
        (Task.priority == Priority.LOW, 3),
        else_=4,
    )


def _task_brief(row: Task) -> dict[str, Any]:
    return {
        "task_id": str(row.id),
        "task_type": row.task_type.value,
        "status": row.status.value,
        "priority": row.priority.value,
        "hitl_pending": row.status == TaskStatus.BLOCKED and row.hitl_required,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


async def _tenant_config_get(redis, tenant_id: UUID) -> dict[str, Any]:
    raw = await redis.get(f"{_TENANT_CONFIG_PREFIX}{tenant_id}")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {"display_name": f"Tenant {str(tenant_id)[:8]}", "llm_tier": "dev"}


async def _tenant_config_set(
    redis, tenant_id: UUID, patch: dict[str, Any]
) -> dict[str, Any]:
    current = await _tenant_config_get(redis, tenant_id)
    current.update(patch)
    await redis.set(f"{_TENANT_CONFIG_PREFIX}{tenant_id}", json.dumps(current))
    return current


@router.get("/encounters", response_model=list[EncounterOption])
async def list_encounters(
    principal: Annotated[AuthPrincipal, Depends(_clinician_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
) -> list[EncounterOption]:
    """Tenant-scoped encounters for SOAP / RCM review encounter pickers."""
    stmt = (
        select(Encounter, Patient)
        .join(Patient, Encounter.patient_id == Patient.id)
        .where(Encounter.tenant_id == principal.tenant_id)
        .order_by(Encounter.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    res = await db.execute(stmt)
    rows = res.all()
    out: list[EncounterOption] = []
    for enc, pat in rows:
        name = (
            " ".join(p for p in (pat.first_name, pat.last_name) if p).strip() or pat.mrn
        )
        fhir_id = enc.fhir_encounter_id
        out.append(
            EncounterOption(
                encounter_id=enc.id,
                fhir_encounter_id=fhir_id,
                patient_name=name,
                status=enc.status.value,
                demo_transcript=_DEMO_TRANSCRIPTS.get(fhir_id or ""),
            )
        )
    return out


@router.post("/demo/bootstrap", response_model=DemoBootstrapResponse)
async def bootstrap_demo_encounter(
    principal: Annotated[AuthPrincipal, Depends(_clinician_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
    patient_handler: Annotated[PatientFhirHandler, Depends(get_patient_handler)],
    encounter_handler: Annotated[EncounterFhirHandler, Depends(get_encounter_handler)],
) -> DemoBootstrapResponse:
    """
    Sync all five HAPI sample patients and encounters into Postgres for local demo flows.

    Requires ``scripts/seed_hapi_fhir.py`` to have been run against the local FHIR server.
    """
    synced: list[DemoBootstrapItem] = []
    try:
        for index in range(1, _DEMO_SAMPLE_COUNT + 1):
            patient_fhir_id = f"healthos-sample-patient-{index:03d}"
            encounter_fhir_id = f"healthos-sample-encounter-{index:03d}"

            remote_patient = await patient_handler.read_fhir(patient_fhir_id)
            patient_row = await patient_handler.upsert_internal_from_fhir(
                db,
                tenant_id=principal.tenant_id,
                principal=principal,
                fhir_patient=remote_patient,
            )
            remote_encounter = await encounter_handler.read_fhir(encounter_fhir_id)
            encounter_row = await encounter_handler.upsert_internal_from_fhir(
                db,
                tenant_id=principal.tenant_id,
                principal=principal,
                fhir_encounter=remote_encounter,
            )

            if not patient_row.fhir_patient_id or not encounter_row.fhir_encounter_id:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Synced rows missing FHIR identifiers",
                )

            synced.append(
                DemoBootstrapItem(
                    internal_patient_id=patient_row.id,
                    internal_encounter_id=encounter_row.id,
                    fhir_patient_id=patient_row.fhir_patient_id,
                    fhir_encounter_id=encounter_row.fhir_encounter_id,
                )
            )

        await db.commit()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Demo bootstrap failed. Ensure HAPI FHIR is running and seeded "
                f"({exc.__class__.__name__}: {exc})"
            ),
        ) from exc

    return DemoBootstrapResponse(synced=synced)


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(
    request: Request,
    principal: Annotated[AuthPrincipal, Depends(_clinician_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DashboardSummary:
    """Admin dashboard overview — task queue stats, HITL count, agent health (#99)."""
    tenant_id = principal.tenant_id

    status_stmt = (
        select(Task.status, func.count())
        .where(Task.tenant_id == tenant_id)
        .group_by(Task.status)
    )
    type_stmt = (
        select(Task.task_type, func.count())
        .where(Task.tenant_id == tenant_id)
        .group_by(Task.task_type)
    )
    hitl_stmt = select(func.count()).where(
        Task.tenant_id == tenant_id,
        Task.status == TaskStatus.BLOCKED,
        Task.hitl_required.is_(True),
    )
    recent_stmt = (
        select(Task)
        .where(Task.tenant_id == tenant_id)
        .order_by(Task.updated_at.desc())
        .limit(12)
    )

    status_res, type_res, hitl_res, recent_res = (
        await db.execute(status_stmt),
        await db.execute(type_stmt),
        await db.execute(hitl_stmt),
        await db.execute(recent_stmt),
    )

    redis_ok = await ping_redis(request.app.state.redis)
    weaviate_ok = ping_weaviate(getattr(request.app.state, "weaviate", None))

    return DashboardSummary(
        tenant_id=tenant_id,
        task_counts_by_status={str(k.value): int(v) for k, v in status_res.all()},
        task_counts_by_type={str(k.value): int(v) for k, v in type_res.all()},
        hitl_pending_count=int(hitl_res.scalar_one()),
        agents={
            "orchestrator": True,
            "documentation": True,
            "rcm": True,
            "redis": redis_ok,
            "weaviate": weaviate_ok,
        },
        recent_tasks=[_task_brief(r) for r in recent_res.scalars().all()],
    )


@router.get("/hitl-queue", response_model=list[HitlQueueItem])
async def hitl_queue(
    principal: Annotated[AuthPrincipal, Depends(_clinician_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, ge=1, le=200),
) -> list[HitlQueueItem]:
    """Tasks awaiting human approval, sorted by priority (#101)."""
    stmt = (
        select(Task)
        .where(
            Task.tenant_id == principal.tenant_id,
            Task.status == TaskStatus.BLOCKED,
            Task.hitl_required.is_(True),
        )
        .order_by(_prio_rank(), Task.created_at.asc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()
    return [
        HitlQueueItem(
            task_id=r.id,
            task_type=r.task_type,
            priority=r.priority,
            status=r.status,
            encounter_id=r.encounter_id,
            patient_id=r.patient_id,
            hitl_required=r.hitl_required,
            confidence_scores=dict(r.confidence_scores or {}),
            agent_outputs=dict(r.agent_outputs or {}),
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.get("/audit-trail", response_model=list[AuditTrailItem])
async def list_audit_trail(
    principal: Annotated[AuthPrincipal, Depends(_clinician_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
    action: str | None = None,
    actor_id: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[AuditTrailItem]:
    """Filterable audit log for admin dashboard and compliance UI (#99, #106)."""
    stmt = select(AuditTrail).where(AuditTrail.tenant_id == principal.tenant_id)
    if action:
        stmt = stmt.where(AuditTrail.action.ilike(f"%{action}%"))
    if actor_id:
        stmt = stmt.where(AuditTrail.actor_id == actor_id)
    if resource_type:
        stmt = stmt.where(AuditTrail.resource_type.ilike(f"%{resource_type}%"))
    if date_from:
        stmt = stmt.where(AuditTrail.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditTrail.created_at <= date_to)
    stmt = stmt.order_by(AuditTrail.created_at.desc()).limit(limit)
    res = await db.execute(stmt)
    rows = res.scalars().all()
    return [
        AuditTrailItem(
            id=r.id,
            task_id=r.task_id,
            actor_id=r.actor_id,
            actor_type=r.actor_type.value,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            event_metadata=dict(r.event_metadata or {}),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/audit-trail/export")
async def export_audit_trail(
    principal: Annotated[AuthPrincipal, Depends(_clinician_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
    action: str | None = None,
    actor_id: str | None = None,
    resource_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(2000, ge=1, le=5000),
) -> StreamingResponse:
    """CSV export of the tenant audit trail for local review."""
    items = await list_audit_trail(
        principal=principal,
        db=db,
        action=action,
        actor_id=actor_id,
        resource_type=resource_type,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "created_at",
            "action",
            "actor_id",
            "actor_type",
            "resource_type",
            "resource_id",
            "task_id",
            "event_metadata",
        ]
    )
    for row in items:
        writer.writerow(
            [
                str(row.id),
                row.created_at.isoformat(),
                row.action,
                row.actor_id or "",
                row.actor_type,
                row.resource_type,
                row.resource_id or "",
                str(row.task_id) if row.task_id else "",
                json.dumps(row.event_metadata),
            ]
        )
    buf.seek(0)
    filename = f"healthos-audit-{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/rcm/tasks/{task_id}/review")
async def rcm_code_review(
    task_id: UUID,
    body: RcmReviewBody,
    principal: Annotated[AuthPrincipal, Depends(_biller_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """
    Approve or override RCM coding suggestions for a completed audit task (#102).

    Persists reviewer decision on the linked ``Claim`` row and appends an audit event.
    """
    res = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == principal.tenant_id)
    )
    task = res.scalar_one_or_none()
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.task_type not in (TaskType.CODE_AUDIT, TaskType.RCM_AUDIT):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Not an RCM audit task")

    report = (task.agent_outputs or {}).get("rcm_audit_report")
    if not isinstance(report, dict):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="RCM audit report not available on this task",
        )

    claim_res = await db.execute(
        select(Claim).where(
            Claim.task_id == task_id,
            Claim.tenant_id == principal.tenant_id,
        )
    )
    claim = claim_res.scalar_one_or_none()

    before_report = dict(report)
    review_meta = {
        "approved": body.approved,
        "override_icd10": body.override_icd10,
        "override_cpt": body.override_cpt,
        "reviewer_notes": body.reviewer_notes,
        "reviewed_at": utc_now().isoformat(),
        "reviewer_id": str(principal.user_id),
    }
    report = dict(report)
    report["human_review"] = review_meta
    if body.override_icd10:
        report["approved_icd10"] = body.override_icd10
    if body.override_cpt:
        report["approved_cpt"] = body.override_cpt

    task.agent_outputs = {**(task.agent_outputs or {}), "rcm_audit_report": report}
    task.updated_by = str(principal.user_id)
    if body.approved:
        task.status = TaskStatus.SUCCEEDED
    else:
        task.status = TaskStatus.FAILED
        task.error_message = body.reviewer_notes or "Rejected by biller review"

    if claim is not None:
        claim.coding_suggestions = report
        claim.status = (
            ClaimStatus.READY_TO_SUBMIT if body.approved else ClaimStatus.DRAFT
        )
        claim.updated_by = str(principal.user_id)

    db.add(
        AuditTrail(
            tenant_id=principal.tenant_id,
            task_id=task_id,
            actor_id=str(principal.user_id),
            actor_type=ActorType.USER,
            action="RCM_CODE_REVIEWED",
            resource_type="claim",
            resource_id=str(claim.id) if claim else str(task_id),
            before={"rcm_audit_report": before_report},
            after={"rcm_audit_report": report, "review": review_meta},
            event_metadata={"approved": body.approved},
            created_at=utc_now(),
        )
    )
    await db.commit()

    return {
        "task_id": str(task_id),
        "claim_id": str(claim.id) if claim else None,
        "approved": body.approved,
        "status": task.status.value,
    }


@router.get("/tenants", response_model=list[dict[str, Any]])
async def list_tenants(
    principal: Annotated[AuthPrincipal, Depends(_admin_roles)],
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict[str, Any]]:
    """Tenant roster with usage counts — admin only (#105)."""
    stmt = (
        select(User.tenant_id, func.count(User.id))
        .group_by(User.tenant_id)
        .order_by(User.tenant_id)
    )
    res = await db.execute(stmt)
    tenant_rows = res.all()
    redis = request.app.state.redis
    out: list[dict[str, Any]] = []
    for tenant_id, user_count in tenant_rows:
        task_count_res = await db.execute(
            select(func.count()).where(Task.tenant_id == tenant_id)
        )
        config = await _tenant_config_get(redis, tenant_id)
        out.append(
            {
                "tenant_id": str(tenant_id),
                "display_name": config.get("display_name"),
                "llm_tier": config.get("llm_tier", "dev"),
                "user_count": int(user_count),
                "task_count": int(task_count_res.scalar_one()),
                "is_current": tenant_id == principal.tenant_id,
            }
        )
    return out


@router.patch("/tenants/{tenant_id}/config")
async def update_tenant_config(
    tenant_id: UUID,
    body: TenantConfigBody,
    principal: Annotated[AuthPrincipal, Depends(_admin_roles)],
    request: Request,
) -> dict[str, Any]:
    """Set per-tenant LLM tier and display name (#105). Stored in Redis."""
    patch: dict[str, Any] = {"llm_tier": body.llm_tier}
    if body.display_name is not None:
        patch["display_name"] = body.display_name
    config = await _tenant_config_set(request.app.state.redis, tenant_id, patch)
    return {"tenant_id": str(tenant_id), "config": config}


@router.get("/prior-auth/board")
async def prior_auth_board(
    principal: Annotated[AuthPrincipal, Depends(_clinician_roles)],
    request: Request,
) -> dict[str, Any]:
    """
    Kanban board data for prior-auth tracker (#104).

    Uses Redis when cards exist; otherwise returns demo placeholder cards until
    the Prior Auth agent (Section F) is implemented.
    """
    redis = request.app.state.redis
    key = f"{_PRIOR_AUTH_PREFIX}{principal.tenant_id}"
    raw = await redis.get(key)
    if raw:
        try:
            cards = json.loads(raw)
            return {"cards": cards, "source": "redis"}
        except json.JSONDecodeError:
            pass
    return {
        "cards": _DEMO_PRIOR_AUTH_CARDS,
        "source": "demo",
        "note": "Prior Auth agent not yet built — showing demo cards. POST /ui/prior-auth/seed to persist.",
    }


@router.post("/prior-auth/seed")
async def seed_prior_auth_board(
    principal: Annotated[AuthPrincipal, Depends(_admin_roles)],
    request: Request,
) -> dict[str, Any]:
    """Persist demo prior-auth Kanban cards to Redis for the current tenant."""
    redis = request.app.state.redis
    key = f"{_PRIOR_AUTH_PREFIX}{principal.tenant_id}"
    await redis.set(key, json.dumps(_DEMO_PRIOR_AUTH_CARDS))
    return {"seeded": len(_DEMO_PRIOR_AUTH_CARDS)}


@router.patch("/prior-auth/cards/{card_id}")
async def move_prior_auth_card(
    card_id: str,
    body: PriorAuthMoveBody,
    principal: Annotated[AuthPrincipal, Depends(_clinician_roles)],
    request: Request,
) -> dict[str, Any]:
    """Move a prior-auth card between Kanban columns (#104)."""
    redis = request.app.state.redis
    key = f"{_PRIOR_AUTH_PREFIX}{principal.tenant_id}"
    raw = await redis.get(key)
    cards = _DEMO_PRIOR_AUTH_CARDS if not raw else json.loads(raw)
    found = False
    for card in cards:
        if card.get("id") == card_id:
            card["column"] = body.column
            if body.column == "submitted" and not card.get("submitted_at"):
                card["submitted_at"] = datetime.now(timezone.utc).isoformat()
            found = True
            break
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Card not found")
    await redis.set(key, json.dumps(cards))
    return {"card_id": card_id, "column": body.column}
