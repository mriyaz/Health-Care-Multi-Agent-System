"""
RCM coding audit specialist — Orchestrator entrypoint for Section E (tasks 52–59).

Produces the structured ``rcm_audit_report`` (#59) and persists a ``Claim`` snapshot
when an encounter context is present.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.graphs.orchestrator.routing import ROUTE_RCM
from api.graphs.orchestrator.state import OrchestratorState
from api.llm.openrouter_client import OpenRouterClient
from api.services.rcm_charge_capture import charge_capture_hints
from api.services.rcm_codes import suggest_icd10_cpt
from api.services.rcm_denial_risk import compute_denial_risk_score
from api.services.rcm_prebill import run_prebill_audit
from api.services.rcm_rules_search import search_payer_rules
from api.services.rcm_shap import phrase_attributions_for_code
from api.services.rcm_validation import validate_codes_against_rules
from api.settings import Settings
from db.enums import ClaimStatus
from db.models.claim import Claim
from db.models.encounter import Encounter

logger = logging.getLogger(__name__)


def _audit_event(
    state: OrchestratorState,
    *,
    action: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "action": action,
        "task_id": state.get("task_id"),
        "tenant_id": state.get("tenant_id"),
        "metadata": metadata,
    }


def _pipeline_ms(state: OrchestratorState, t0: float) -> dict[str, Any]:
    return {"latency_ms": round((time.perf_counter() - t0) * 1000.0, 2)}


async def run_rcm_specialist(
    session: AsyncSession,
    state: OrchestratorState,
    settings: Settings,
    openrouter: OpenRouterClient | None,
    weaviate_client: Any,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    route = state.get("specialist_route") or ""
    if route != ROUTE_RCM:
        return {}

    intake = state.get("rcm_intake") or {}
    if not isinstance(intake, dict):
        return _rcm_err(state, "invalid_rcm_intake", settings, t0)

    note = str(intake.get("clinical_note_text") or "").strip()
    if not note:
        return _rcm_err(state, "missing_clinical_note_text", settings, t0)

    specialty = str(intake.get("specialty") or "GENERAL").upper()
    payer = str(intake.get("payer_org_identifier") or "UNKNOWN_PAYER").strip()
    proc = intake.get("procedure_description")
    proc_s = str(proc).strip() if proc else None

    encounter_id_s = state.get("encounter_id")
    tenant_id_s = state.get("tenant_id")
    task_id_s = state.get("task_id")

    suggestions = await suggest_icd10_cpt(
        clinical_note=note,
        specialty=specialty,
        procedure_description=proc_s,
        openrouter=openrouter,
        settings=settings,
        state=state,
    )

    icd_list = suggestions.get("icd10") or []
    cpt_list = suggestions.get("cpt") or []

    existing_icd = intake.get("existing_icd10")
    existing_cpt = intake.get("existing_cpt")
    if isinstance(existing_icd, list) and existing_icd:
        primary_icd = str(existing_icd[0]).strip()
    elif icd_list:
        primary_icd = str(icd_list[0].get("code") or "").strip()
    else:
        primary_icd = ""

    if isinstance(existing_cpt, list) and existing_cpt:
        primary_cpt = str(existing_cpt[0]).strip()
    elif cpt_list:
        primary_cpt = str(cpt_list[0].get("code") or "").strip()
    else:
        primary_cpt = ""

    all_icd = []
    if isinstance(existing_icd, list):
        all_icd.extend(str(x) for x in existing_icd)
    all_icd.extend(str(x.get("code")) for x in icd_list if isinstance(x, dict))
    all_cpt = []
    if isinstance(existing_cpt, list):
        all_cpt.extend(str(x) for x in existing_cpt)
    all_cpt.extend(str(x.get("code")) for x in cpt_list if isinstance(x, dict))

    sug_cpt_only = [str(x.get("code")) for x in cpt_list if isinstance(x, dict)]
    capture_hints = charge_capture_hints(note, sug_cpt_only)

    top_icd_desc = ""
    if icd_list and isinstance(icd_list[0], dict):
        top_icd_desc = str(icd_list[0].get("description") or "")
    top_cpt_desc = ""
    top_cpt_entry: dict[str, Any] | None = None
    if cpt_list and isinstance(cpt_list[0], dict):
        top_cpt_entry = cpt_list[0]
        top_cpt_desc = str(cpt_list[0].get("description") or "")

    shap_icd = phrase_attributions_for_code(
        note, code=primary_icd or "PRIMARY", description=top_icd_desc or primary_icd
    )
    shap_cpt = phrase_attributions_for_code(
        note, code=primary_cpt or "PRIMARY", description=top_cpt_desc or primary_cpt
    )

    rules = search_payer_rules(
        weaviate_client,
        tenant_id=str(tenant_id_s or ""),
        payer_org_identifier=payer,
        clinical_note_excerpt=note,
        cpt_hint=primary_cpt,
        icd_hint=primary_icd,
        limit=14,
    )

    validation = validate_codes_against_rules(
        primary_icd=primary_icd,
        primary_cpt=primary_cpt,
        all_icd=all_icd,
        all_cpt=all_cpt,
        retrieved_rules=rules,
    )

    prebill = run_prebill_audit(
        clinical_note=note,
        primary_icd=primary_icd,
        primary_cpt=primary_cpt,
        validation=validation,
        cpt_entry=top_cpt_entry,
        payer_org=payer,
    )

    icd_conf = float(icd_list[0].get("confidence")) if icd_list else 0.5
    cpt_conf = float(cpt_list[0].get("confidence")) if cpt_list else 0.5
    cpt_risks = list((top_cpt_entry or {}).get("risk_flags") or [])

    denial = compute_denial_risk_score(
        icd_confidence=icd_conf,
        cpt_confidence=cpt_conf,
        validation=validation,
        prebill_score_ratio=float(prebill.get("score_ratio") or 0.0),
        cpt_risk_flags=cpt_risks,
    )

    actions: list[str] = []
    if not validation.get("validation_ok"):
        actions.append(
            "Review LCD mismatch flags with certified coder before submission."
        )
    if denial.get("risk_score", 0) > 0.55:
        actions.append("High denial risk — strengthen documentation or adjust coding.")
    for r in validation.get("reasons") or []:
        if isinstance(r, dict) and r.get("severity") == "high":
            actions.append(f"Policy concern: {r.get('reason_code')}")

    report: dict[str, Any] = {
        "version": "1.0",
        "specialty": specialty,
        "payer_org_identifier": payer,
        "icd10_suggestions": icd_list,
        "cpt_suggestions": cpt_list,
        "shap_explanations": {
            "icd10_primary": shap_icd,
            "cpt_primary": shap_cpt,
            "shap_note": "LOO-marginal lexical proxy — swap for transformer SHAP in production.",
        },
        "payer_rules_retrieved": rules[:8],
        "validation": validation,
        "prebill_audit": prebill,
        "denial_risk": denial,
        "recommended_actions": actions[:12],
        "coding_model": suggestions.get("model_used"),
        "clinicalbert_equivalent": suggestions.get("clinicalbert_equivalent"),
        "charge_capture_completeness": capture_hints,
    }

    preview = json.dumps(
        {
            "tenant_id": tenant_id_s,
            "task_id": task_id_s,
            "primary_icd": primary_icd,
            "primary_cpt": primary_cpt,
        },
        sort_keys=True,
    )
    input_hash = hashlib.sha256(preview.encode()).hexdigest()

    combined_conf = max(
        0.0,
        min(
            1.0,
            ((icd_conf + cpt_conf) / 2.0)
            * (1.0 - 0.45 * float(denial.get("risk_score") or 0.0)),
        ),
    )

    model_versions = dict(state.get("model_versions") or {})
    model_versions["rcm_coding_model"] = suggestions.get("model_used")
    model_versions["rcm_denial_model"] = denial.get("model_kind")

    pending = list(state.get("pending_audit_events") or [])
    pending.append(
        _audit_event(
            state,
            action="RCM_AUDIT_COMPLETED",
            metadata={
                "input_hash": input_hash,
                "denial_risk": denial.get("risk_score"),
                "validation_ok": validation.get("validation_ok"),
            },
        )
    )

    agent_outputs = dict(state.get("agent_outputs") or {})
    agent_outputs["specialist"] = {
        "route": ROUTE_RCM,
        "summary": json.dumps({"primary_icd": primary_icd, "primary_cpt": primary_cpt}),
        "stub": suggestions.get("source") == "stub",
    }
    agent_outputs["rcm_audit_report"] = report

    step = int(state.get("step_count") or 0) + 1

    out: dict[str, Any] = {
        "step_count": step,
        "agent_outputs": agent_outputs,
        "confidence_scores": {"specialist": combined_conf},
        "model_versions": model_versions,
        "tokens_used": int(state.get("tokens_used") or 0),
        "input_hash": input_hash,
        "pending_audit_events": pending,
        **_pipeline_ms(state, t0),
    }

    # Persist Claim when encounter is resolvable
    if encounter_id_s and tenant_id_s:
        try:
            enc_uuid = UUID(str(encounter_id_s))
            tenant_uuid = UUID(str(tenant_id_s))
            task_uuid = UUID(str(task_id_s)) if task_id_s else None
            res = await session.execute(
                select(Encounter).where(
                    Encounter.id == enc_uuid,
                    Encounter.tenant_id == tenant_uuid,
                )
            )
            enc = res.scalar_one_or_none()
            if enc is not None and task_uuid:
                res_c = await session.execute(
                    select(Claim).where(
                        Claim.task_id == task_uuid,
                        Claim.tenant_id == tenant_uuid,
                    )
                )
                row = res_c.scalar_one_or_none()
                payload = {
                    "payer_org_identifier": payer,
                    "report_version": report["version"],
                }
                denial_meta = dict(denial)
                val_meta = dict(validation)
                if row is None:
                    session.add(
                        Claim(
                            tenant_id=tenant_uuid,
                            encounter_id=enc_uuid,
                            task_id=task_uuid,
                            status=ClaimStatus.DRAFT,
                            payer_name=payer[:200],
                            coding_suggestions=report,
                            payer_payload=payload,
                            denial_metadata=denial_meta,
                            validation_metadata=val_meta,
                            model_metadata=dict(model_versions),
                            created_by="RCM_AGENT",
                            updated_by="RCM_AGENT",
                        )
                    )
                else:
                    row.coding_suggestions = report
                    row.denial_metadata = denial_meta
                    row.validation_metadata = val_meta
                    row.model_metadata = dict(model_versions)
                    row.payer_payload = {**dict(row.payer_payload or {}), **payload}
                    row.updated_by = "RCM_AGENT"
        except Exception:
            logger.exception("rcm_claim_persist_failed")

    return out


def _rcm_err(
    state: OrchestratorState,
    code: str,
    settings: Settings,
    t0: float,
) -> dict[str, Any]:
    pending = list(state.get("pending_audit_events") or [])
    pending.append(
        _audit_event(
            state,
            action="RCM_AUDIT_FAILED",
            metadata={"error": code},
        )
    )
    return {
        "status": "FAILED",
        "error_message": code,
        "agent_outputs": dict(state.get("agent_outputs") or {}),
        "confidence_scores": dict(state.get("confidence_scores") or {}),
        "model_versions": dict(state.get("model_versions") or {}),
        "pending_audit_events": pending,
        **_pipeline_ms(state, t0),
    }
