"""
RCM operational endpoints (Section E — P1 tasks #60–63): denial queue, recode stub, analytics.

These complement the core audit task API; responses are tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import get_current_active_principal
from api.auth.principal import AuthPrincipal
from api.deps import get_db
from api.services.rcm_codes import suggest_icd10_cpt
from api.services.rcm_denial_risk import compute_denial_risk_score
from api.services.rcm_prebill import run_prebill_audit
from api.services.rcm_rules_search import search_payer_rules
from api.services.rcm_validation import validate_codes_against_rules
from api.graphs.orchestrator.state import OrchestratorState
from api.settings import Settings
from db.enums import ClaimStatus
from db.models.claim import Claim

router = APIRouter(prefix="/rcm", tags=["rcm-admin"])


class DenialRegisterBody(BaseModel):
    claim_id: UUID
    denial_reason: str = Field(..., min_length=3, max_length=4000)
    payer_reason_code: str | None = None
    categorization: str | None = Field(
        None,
        description="e.g. medical_necessity | coding | timely_filing | bundling",
    )


class RecodeRequestBody(BaseModel):
    notes: str | None = None
    #: When true, enqueue a new CODE_AUDIT task (implemented in v1.1 — returns hint for now)
    request_new_audit: bool = False


class PredictDenialBody(BaseModel):
    clinical_note_text: str = Field(..., min_length=10)
    specialty: str = "GENERAL"
    payer_org_identifier: str = "UNKNOWN_PAYER"
    procedure_description: str | None = None


@router.get("/denials", response_model=list[dict[str, Any]])
async def list_denial_queue(
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Claims in ``DENIED`` status for triage into appeal vs recode (checklist #60)."""
    lim = max(1, min(limit, 200))
    stmt = (
        select(Claim)
        .where(
            Claim.tenant_id == principal.tenant_id,
            Claim.status == ClaimStatus.DENIED,
        )
        .order_by(Claim.updated_at.desc())
        .limit(lim)
    )
    res = await db.execute(stmt)
    rows = res.scalars().all()
    out: list[dict[str, Any]] = []
    for c in rows:
        out.append(
            {
                "claim_id": str(c.id),
                "encounter_id": str(c.encounter_id),
                "task_id": str(c.task_id) if c.task_id else None,
                "status": c.status.value,
                "denial_reason": c.denial_reason,
                "denial_metadata": dict(c.denial_metadata or {}),
                "coding_suggestions_summary": (
                    (c.coding_suggestions or {}).get("version")
                    if isinstance(c.coding_suggestions, dict)
                    else None
                ),
                "updated_at": c.updated_at.isoformat(),
            }
        )
    return out


@router.post("/denials", status_code=status.HTTP_202_ACCEPTED)
async def register_denial(
    body: DenialRegisterBody,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """Attach payer denial metadata to an existing claim row (#60 intake)."""
    res = await db.execute(
        select(Claim).where(
            Claim.id == body.claim_id,
            Claim.tenant_id == principal.tenant_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Claim not found")
    row.status = ClaimStatus.DENIED
    row.denial_reason = body.denial_reason
    meta = dict(row.denial_metadata or {})
    meta["payer_reason_code"] = body.payer_reason_code
    meta["categorization"] = body.categorization
    meta["registered_at"] = datetime.now(timezone.utc).isoformat()
    row.denial_metadata = meta
    row.updated_by = str(principal.user_id)
    await db.commit()
    return {"claim_id": str(row.id), "status": row.status.value}


@router.post("/denials/{claim_id}/recode")
async def recode_denied_claim(
    claim_id: UUID,
    body: RecodeRequestBody,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    """
    Stub for automated recode + resubmission workflow (#61).

    Full automation queues ``CODE_AUDIT`` with HITL — wire Orchestrator task creation here later.
    """
    res = await db.execute(
        select(Claim).where(
            Claim.id == claim_id,
            Claim.tenant_id == principal.tenant_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Claim not found")
    meta = dict(row.denial_metadata or {})
    meta["recode_requested_at"] = datetime.now(timezone.utc).isoformat()
    meta["recode_notes"] = body.notes
    meta["hitl_required"] = True
    row.denial_metadata = meta
    row.updated_by = str(principal.user_id)
    await db.commit()
    return {
        "claim_id": str(row.id),
        "message": "Recode logged — enqueue CODE_AUDIT task from billing UI when orchestration is enabled.",
        "request_new_audit": body.request_new_audit,
    }


@router.get("/analytics/summary", response_model=dict[str, Any])
async def rcm_analytics_summary(
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    payer: str | None = Query(None, description="Filter by payer_name (partial match)"),
) -> dict[str, Any]:
    """Aggregate claim metrics with optional date/payer filters (#63, #103)."""
    status_stmt = select(Claim.status, func.count()).where(
        Claim.tenant_id == principal.tenant_id
    )
    if date_from:
        status_stmt = status_stmt.where(Claim.created_at >= date_from)
    if date_to:
        status_stmt = status_stmt.where(Claim.created_at <= date_to)
    if payer:
        status_stmt = status_stmt.where(Claim.payer_name.ilike(f"%{payer}%"))
    status_stmt = status_stmt.group_by(Claim.status)
    res = await db.execute(status_stmt)
    pairs = res.all()
    by_status = {str(k.value): int(v) for k, v in pairs}
    total = sum(by_status.values())
    denied = by_status.get(ClaimStatus.DENIED.value, 0)
    paid = by_status.get(ClaimStatus.PAID.value, 0)
    submitted = by_status.get(ClaimStatus.SUBMITTED.value, 0)
    accepted = by_status.get(ClaimStatus.ACCEPTED.value, 0)
    first_pass_proxy = (
        round(paid / max(1, paid + denied), 4) if (paid + denied) else None
    )
    recovery_rate = round(paid / max(1, denied), 4) if denied else None

    # Denial rate by payer
    payer_stmt = select(Claim.payer_name, func.count()).where(
        Claim.tenant_id == principal.tenant_id,
        Claim.status == ClaimStatus.DENIED,
    )
    if date_from:
        payer_stmt = payer_stmt.where(Claim.created_at >= date_from)
    if date_to:
        payer_stmt = payer_stmt.where(Claim.created_at <= date_to)
    if payer:
        payer_stmt = payer_stmt.where(Claim.payer_name.ilike(f"%{payer}%"))
    payer_stmt = payer_stmt.group_by(Claim.payer_name).order_by(func.count().desc())
    payer_res = await db.execute(payer_stmt)
    denial_by_payer = {(name or "UNKNOWN"): int(cnt) for name, cnt in payer_res.all()}

    # Denial rate by CPT (from coding_suggestions JSON)
    claim_stmt = select(Claim).where(
        Claim.tenant_id == principal.tenant_id,
        Claim.status == ClaimStatus.DENIED,
    )
    if date_from:
        claim_stmt = claim_stmt.where(Claim.created_at >= date_from)
    if date_to:
        claim_stmt = claim_stmt.where(Claim.created_at <= date_to)
    if payer:
        claim_stmt = claim_stmt.where(Claim.payer_name.ilike(f"%{payer}%"))
    claim_res = await db.execute(claim_stmt.limit(500))
    cpt_counts: dict[str, int] = {}
    revenue_at_risk = 0.0
    for row in claim_res.scalars().all():
        suggestions = row.coding_suggestions or {}
        cpt_list = suggestions.get("cpt_suggestions") or []
        if cpt_list and isinstance(cpt_list[0], dict):
            code = str(cpt_list[0].get("code") or "UNKNOWN")
            cpt_counts[code] = cpt_counts.get(code, 0) + 1
        risk = (row.denial_metadata or {}).get("risk_score")
        if isinstance(risk, (int, float)):
            revenue_at_risk += float(risk) * 250.0  # illustrative $/claim

    return {
        "tenant_id": str(principal.tenant_id),
        "claims_by_status": by_status,
        "total_claims": total,
        "first_pass_rate_proxy": first_pass_proxy,
        "denied_count": denied,
        "submitted_count": submitted,
        "paid_count": paid,
        "accepted_count": accepted,
        "recovery_rate_proxy": recovery_rate,
        "denial_by_payer": denial_by_payer,
        "denial_by_cpt": dict(
            sorted(cpt_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        ),
        "revenue_at_risk_usd": round(revenue_at_risk, 2),
        "filters": {
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "payer": payer,
        },
        "note": "Metrics are illustrative until 835/277 remittance data is ingested.",
    }


@router.post("/predict-denial", response_model=dict[str, Any])
async def predict_denial_ml(
    body: PredictDenialBody,
    request: Request,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
) -> dict[str, Any]:
    """
    Lightweight denial likelihood estimate using the same heuristic engine as the audit task (#62).

    Does not persist PHI beyond request scope; tenant id is only traced in logs when configured.
    """
    settings: Settings = request.app.state.settings
    openrouter = getattr(request.app.state, "openrouter", None)
    wv = getattr(request.app.state, "weaviate", None)

    minimal_state: OrchestratorState = {
        "task_id": "predict-ephemeral",
        "tenant_id": str(principal.tenant_id),
        "task_type": "CODE_AUDIT",
    }

    suggestions = await suggest_icd10_cpt(
        clinical_note=body.clinical_note_text,
        specialty=body.specialty,
        procedure_description=body.procedure_description,
        openrouter=openrouter,
        settings=settings,
        state=minimal_state,
    )
    icd_list = suggestions.get("icd10") or []
    cpt_list = suggestions.get("cpt") or []
    primary_icd = str(icd_list[0].get("code")) if icd_list else ""
    primary_cpt = str(cpt_list[0].get("code")) if cpt_list else ""
    all_icd = [str(x.get("code")) for x in icd_list if isinstance(x, dict)]
    all_cpt = [str(x.get("code")) for x in cpt_list if isinstance(x, dict)]

    rules = search_payer_rules(
        wv,
        tenant_id=str(principal.tenant_id),
        payer_org_identifier=body.payer_org_identifier,
        clinical_note_excerpt=body.clinical_note_text,
        cpt_hint=primary_cpt,
        icd_hint=primary_icd,
        limit=12,
    )
    validation = validate_codes_against_rules(
        primary_icd=primary_icd,
        primary_cpt=primary_cpt,
        all_icd=all_icd,
        all_cpt=all_cpt,
        retrieved_rules=rules,
    )
    top_cpt = cpt_list[0] if cpt_list else {}
    prebill = run_prebill_audit(
        clinical_note=body.clinical_note_text,
        primary_icd=primary_icd,
        primary_cpt=primary_cpt,
        validation=validation,
        cpt_entry=top_cpt if isinstance(top_cpt, dict) else None,
        payer_org=body.payer_org_identifier,
    )
    icd_conf = float(icd_list[0].get("confidence")) if icd_list else 0.5
    cpt_conf = float(cpt_list[0].get("confidence")) if cpt_list else 0.5
    cpt_risks = list(
        (top_cpt.get("risk_flags") or []) if isinstance(top_cpt, dict) else []
    )
    denial = compute_denial_risk_score(
        icd_confidence=icd_conf,
        cpt_confidence=cpt_conf,
        validation=validation,
        prebill_score_ratio=float(prebill.get("score_ratio") or 0.0),
        cpt_risk_flags=cpt_risks,
    )
    return {
        "suggestions": {"icd10": icd_list, "cpt": cpt_list},
        "denial_risk": denial,
        "validation": validation,
        "prebill_audit": prebill,
        "model_note": "Train supervised model on 835/277 outcomes to replace heuristic.",
    }
