"""
End-to-end Clinical Documentation pipeline invoked from the Orchestrator (Section D).

Transcribe → de-identify → LLM generate → validate → persist ``Note`` (draft / review).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.graphs.orchestrator.routing import ROUTE_DOCUMENT
from api.graphs.orchestrator.state import OrchestratorState
from api.llm.openrouter_client import OpenRouterClient
from api.services.documentation_llm import (
    discharge_payload_to_soap_shape,
    generate_discharge_summary,
    generate_referral_letter,
    generate_soap_note,
    referral_payload_to_soap_shape,
    soap_payload_to_note_soap,
)
from api.services.note_quality import (
    combined_documentation_confidence,
    validate_soap_structure,
)
from api.services.phi_deidentify import deidentify_clinical_text, relink_json_values
from api.services.whisper_tool import (
    should_skip_whisper,
    transcribe_audio_file,
    whisper_available,
)
from api.settings import Settings
from db.enums import NoteStatus
from db.models.encounter import Encounter
from db.models.note import Note

logger = logging.getLogger(__name__)

_DOCUMENT_KINDS = frozenset({"soap", "discharge_summary", "referral"})


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


async def run_documentation_specialist(
    session: AsyncSession,
    state: OrchestratorState,
    settings: Settings,
    openrouter: OpenRouterClient | None,
) -> dict[str, Any]:
    """
    Execute documentation flow for ``ROUTE_DOCUMENT``.

    Expects ``document_intake`` in state (from ``Task.agent_state``) and
    ``encounter_id`` / ``tenant`` context on the Task row.
    """
    t_pipeline0 = time.perf_counter()
    route = state.get("specialist_route") or ""
    if route != ROUTE_DOCUMENT:
        return {}

    intake = state.get("document_intake") or {}
    if not isinstance(intake, dict):
        return _doc_error(
            state, "invalid_document_intake", settings, pipeline_ms(state, t_pipeline0)
        )

    task_id = state.get("task_id")
    tenant_id = state.get("tenant_id")
    enc_id = state.get("encounter_id")
    if not tenant_id:
        return _doc_error(
            state, "missing_tenant_id", settings, pipeline_ms(state, t_pipeline0)
        )
    if not enc_id:
        return _doc_error(
            state, "missing_encounter_id", settings, pipeline_ms(state, t_pipeline0)
        )

    try:
        encounter_uuid = UUID(str(enc_id))
        tenant_uuid = UUID(str(tenant_id))
    except (TypeError, ValueError):
        return _doc_error(
            state, "invalid_uuid_context", settings, pipeline_ms(state, t_pipeline0)
        )

    res = await session.execute(
        select(Encounter).where(
            Encounter.id == encounter_uuid,
            Encounter.tenant_id == tenant_uuid,
        )
    )
    encounter = res.scalar_one_or_none()
    if encounter is None:
        return _doc_error(
            state, "encounter_not_found", settings, pipeline_ms(state, t_pipeline0)
        )

    kind = str(intake.get("note_kind") or "soap").lower()
    if kind not in _DOCUMENT_KINDS:
        kind = "soap"
    specialty = str(intake.get("specialty") or "GENERAL")

    # --- Transcript (#38, #39) ---
    transcript = (intake.get("transcript") or "").strip()
    audio_path = intake.get("audio_path")
    ap_for_cleanup: str | None = None
    try:
        if not transcript and audio_path:
            if should_skip_whisper() or not whisper_available():
                return _doc_error(
                    state,
                    "whisper_unavailable_or_skipped",
                    settings,
                    pipeline_ms(state, t_pipeline0),
                )
            ap = str(audio_path)
            ap_for_cleanup = ap
            if not os.path.isfile(ap):
                return _doc_error(
                    state,
                    "audio_file_missing",
                    settings,
                    pipeline_ms(state, t_pipeline0),
                )
            tr = await asyncio.to_thread(
                transcribe_audio_file,
                ap,
                model_name=settings.whisper_model_name,
            )
            transcript = str(tr.get("text") or "")
            if not transcript:
                return _doc_error(
                    state,
                    "empty_transcription",
                    settings,
                    pipeline_ms(state, t_pipeline0),
                )

        if not transcript:
            return _doc_error(
                state, "missing_transcript", settings, pipeline_ms(state, t_pipeline0)
            )
    finally:
        if ap_for_cleanup and os.path.isfile(ap_for_cleanup):
            try:
                os.unlink(ap_for_cleanup)
            except OSError:
                pass

    # --- De-identify (#40) ---
    de = deidentify_clinical_text(transcript)
    extra = intake.get("extra_context") or {}
    if not isinstance(extra, dict):
        extra = {}
    bundle = de.text
    if extra:
        bundle = (
            de.text
            + "\n\nContext JSON (de-identify manually limited):\n"
            + json.dumps(extra, default=str)[:12_000]
        )

    # --- LLM generation (#41, #46, #47) ---
    tokens_used = int(state.get("tokens_used") or 0)
    model_used = settings.documentation_soap_model
    usage_last: dict[str, Any] = {}
    latencies: list[int] = []
    token_total = 0.0
    content_conf = 0.75

    if kind == "soap":
        if not settings.resolved_openrouter_api_key or openrouter is None:
            soap = {
                "subjective": f"Auto draft (no LLM key): {de.text[:500]}",
                "objective": "Not recorded.",
                "assessment": "See subjective.",
                "plan": "Follow up as clinically appropriate.",
            }
            note_soap = soap_payload_to_note_soap(
                {**soap, "icd10_suggestions": [], "confidence": 0.4}
            )
            model_used = "stub"
            content_conf = 0.4
        else:
            try:
                payload, model_used, lat1, t1, u1 = await generate_soap_note(
                    settings=settings,
                    openrouter=openrouter,
                    deidentified_transcript=bundle,
                    specialty=specialty,
                )
            except Exception as exc:
                logger.exception(
                    "soap_generation_failed",
                    extra={
                        "task_id": task_id,
                        "model": settings.documentation_soap_model,
                    },
                )
                detail = str(exc).strip()[:800]
                return _doc_error(
                    state,
                    f"soap_llm_failed:{detail or exc.__class__.__name__}",
                    settings,
                    pipeline_ms(state, t_pipeline0),
                )
            latencies.append(lat1)
            token_total += t1
            usage_last = u1
            rel = relink_json_values(soap_payload_to_note_soap(payload), de.token_map)
            note_soap = rel
            content_conf = float(payload.get("confidence") or 0.75)
    elif kind == "discharge_summary":
        if not settings.resolved_openrouter_api_key or openrouter is None:
            note_soap = discharge_payload_to_soap_shape(
                {
                    "summary": transcript[:2000],
                    "diagnosis_list": [],
                    "medications": [],
                    "follow_up": "",
                    "patient_instructions": "",
                    "confidence": 0.4,
                }
            )
            model_used = "stub"
            content_conf = 0.4
        else:
            payload, model_used, lat1, t1, u1 = await generate_discharge_summary(
                settings=settings,
                openrouter=openrouter,
                deidentified_bundle=bundle,
                specialty=specialty,
            )
            latencies.append(lat1)
            token_total += t1
            usage_last = u1
            note_soap = relink_json_values(
                discharge_payload_to_soap_shape(payload), de.token_map
            )
            content_conf = float(payload.get("confidence") or 0.75)
    else:  # referral
        if not settings.resolved_openrouter_api_key or openrouter is None:
            note_soap = referral_payload_to_soap_shape(
                {
                    "letter_body": transcript[:2000],
                    "reason_for_referral": "",
                    "relevant_history": "",
                    "confidence": 0.4,
                }
            )
            model_used = "stub"
            content_conf = 0.4
        else:
            payload, model_used, lat1, t1, u1 = await generate_referral_letter(
                settings=settings,
                openrouter=openrouter,
                deidentified_bundle=bundle,
                specialty=specialty,
            )
            latencies.append(lat1)
            token_total += t1
            usage_last = u1
            note_soap = relink_json_values(
                referral_payload_to_soap_shape(payload), de.token_map
            )
            content_conf = float(payload.get("confidence") or 0.75)

    struct_conf, sections_flagged = validate_soap_structure(note_soap)
    final_conf = combined_documentation_confidence(content_conf, struct_conf)
    if kind in ("discharge_summary", "referral"):
        # PRD: HITL required for these (#46, #47) — force review if not already low conf
        if final_conf > 0.79:
            final_conf = 0.79

    # --- Persist note ---
    title_map = {
        "soap": "SOAP Note",
        "discharge_summary": "Discharge Summary",
        "referral": "Referral Letter",
    }
    note = Note(
        encounter_id=encounter_uuid,
        task_id=UUID(str(task_id)) if task_id else None,
        status=NoteStatus.IN_REVIEW,
        title=title_map.get(kind, "Clinical Note"),
        content_text="\n\n".join(
            [
                str(note_soap.get("subjective") or ""),
                str(note_soap.get("objective") or ""),
                str(note_soap.get("assessment") or ""),
                str(note_soap.get("plan") or ""),
            ]
        ),
        soap=note_soap,
        validation_metadata={
            "note_kind": kind,
            "sections_flagged": sections_flagged,
            "structural_confidence": struct_conf,
            "original_intake": {
                "note_kind": kind,
                "specialty": specialty,
                "had_audio": bool(audio_path),
            },
        },
        model_metadata={
            "model_used": model_used,
            "confidence_score": final_conf,
            "sections_flagged": sections_flagged,
            "token_count": int(token_total) if token_total else None,
            "latency_ms": sum(latencies) if latencies else None,
            "usage_last": usage_last,
            "pipeline_ms": int((time.perf_counter() - t_pipeline0) * 1000),
        },
        tenant_id=tenant_uuid,
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)

    ph = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "task_id": str(task_id),
            "note_id": str(note.id),
        },
        sort_keys=True,
    )
    input_hash = hashlib.sha256(ph.encode()).hexdigest()

    pending = list(state.get("pending_audit_events") or [])
    pending.append(
        _audit_event(
            state,
            action="DOCUMENTATION_COMPLETED",
            metadata={
                "note_id": str(note.id),
                "model_version": model_used,
                "confidence": final_conf,
                "input_hash": input_hash,
            },
        )
    )

    agent_outputs = dict(state.get("agent_outputs") or {})
    agent_outputs["documentation"] = {
        "note_id": str(note.id),
        "note_kind": kind,
        "soap": note_soap,
    }
    confidence_scores = dict(state.get("confidence_scores") or {})
    confidence_scores["documentation"] = final_conf
    # Back-compat with generic specialist gate: mirror under "specialist"
    confidence_scores["specialist"] = final_conf

    model_versions = dict(state.get("model_versions") or {})
    model_versions["documentation_model"] = model_used
    model_versions["documentation"] = {
        "model_used": model_used,
        "confidence_score": final_conf,
        "sections_flagged": sections_flagged,
        "token_count": int(token_total) if token_total else 0,
        "latency_ms": int(sum(latencies)) if latencies else 0,
    }

    tokens_used = int(
        min(
            int(
                state.get("token_budget") or settings.orchestrator_token_budget_default
            ),
            tokens_used + int(token_total or 0),
        )
    )

    return {
        "step_count": int(state.get("step_count") or 0) + 1,
        "agent_outputs": agent_outputs,
        "confidence_scores": confidence_scores,
        "model_versions": model_versions,
        "tokens_used": tokens_used,
        "input_hash": input_hash,
        "pending_audit_events": pending,
    }


def pipeline_ms(state: OrchestratorState, t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _doc_error(
    state: OrchestratorState,
    code: str,
    settings: Settings,
    pipeline_ms_val: int,
) -> dict[str, Any]:
    """Deterministic failure path (still auditable)."""
    agent_outputs = dict(state.get("agent_outputs") or {})
    agent_outputs["documentation"] = {"error": code}
    pending = list(state.get("pending_audit_events") or [])
    pending.append(
        _audit_event(
            state,
            action="DOCUMENTATION_FAILED",
            metadata={"code": code, "pipeline_ms": pipeline_ms_val},
        )
    )
    return {
        "agent_outputs": agent_outputs,
        "confidence_scores": {
            **dict(state.get("confidence_scores") or {}),
            "specialist": 0.0,
            "documentation": 0.0,
        },
        "model_versions": {
            **dict(state.get("model_versions") or {}),
            "documentation": {"error": code, "pipeline_ms": pipeline_ms_val},
        },
        "error_message": code,
        "status": "FAILED",
    }
