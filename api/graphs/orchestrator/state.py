"""Typed LangGraph state for the Orchestrator agent (Section C — checklist #27)."""

from __future__ import annotations

from typing import Any

from typing_extensions import TypedDict


class OrchestratorState(TypedDict, total=False):
    """
    Shared orchestration state persisted via LangGraph checkpoints.

    Fields align with PRD §7.1 / checklist: task context, tenant isolation,
    specialist outputs, HITL, confidence/model provenance, and routing safety.
    """

    task_id: str
    task_type: str
    tenant_id: str
    patient_id: str | None
    encounter_id: str | None
    status: str

    agent_outputs: dict[str, Any]
    confidence_scores: dict[str, Any]
    model_versions: dict[str, Any]

    hitl_required: bool
    tokens_used: int
    token_budget: int

    route_history: list[str]
    last_route_key: str | None
    routing_repeat_streak: int
    loop_detected: bool

    step_count: int
    transient_retries: int

    input_hash: str | None
    error_message: str | None

    pending_audit_events: list[dict[str, Any]]

    specialist_route: str

    #: Intake payload for Clinical Documentation (audio path, transcript, kind).
    document_intake: dict[str, Any]

    #: Intake payload for Revenue Cycle / coding audit (Section E).
    rcm_intake: dict[str, Any]
