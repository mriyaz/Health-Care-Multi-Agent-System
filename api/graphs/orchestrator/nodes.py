"""Orchestrator LangGraph nodes: routing, specialist stubs, HITL, retries (Section C)."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx
from langgraph.types import interrupt
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from api.graphs.orchestrator.routing import (
    ROUTE_DOCUMENT,
    ROUTE_RCM,
    task_type_to_route,
)
from api.graphs.orchestrator.state import OrchestratorState
from api.llm.openrouter_client import OpenRouterClient
from api.services.documentation_specialist import run_documentation_specialist
from api.services.rcm_specialist import run_rcm_specialist
from api.settings import Settings

logger = logging.getLogger(__name__)

_PRIMARY_RETRY_EXC = (
    httpx.TimeoutException,
    httpx.TransportError,
)


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


def _usage_tokens(usage: Any) -> int:
    if not usage:
        return 0
    if isinstance(usage, dict):
        raw = usage.get("total_tokens")
        if raw is not None:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    return 0


async def route_task_node(state: OrchestratorState) -> dict[str, Any]:
    """Increment step budget, record routing choice, detect trivial routing loops."""
    step = int(state.get("step_count") or 0) + 1
    if step > 25:
        ev = _audit_event(
            state,
            action="ROUTING_STEP_LIMIT",
            metadata={"step_count": step},
        )
        return {
            "step_count": step,
            "loop_detected": True,
            "status": "FAILED",
            "error_message": "orchestrator_step_limit_exceeded",
            "pending_audit_events": list(state.get("pending_audit_events") or [])
            + [ev],
        }

    tt = state.get("task_type")
    if not tt:
        return {
            "loop_detected": True,
            "status": "FAILED",
            "error_message": "missing_task_type",
        }

    route_key = task_type_to_route(tt)
    hist = list(state.get("route_history") or [])
    hist.append(route_key)
    last = state.get("last_route_key")
    streak = (
        int(state.get("routing_repeat_streak") or 0) + 1 if route_key == last else 1
    )
    loop = streak >= 6
    ev = _audit_event(
        state,
        action="ROUTE_SELECT",
        metadata={"route_key": route_key, "route_streak": streak},
    )
    pending = list(state.get("pending_audit_events") or [])
    pending.append(ev)
    out: dict[str, Any] = {
        "step_count": step,
        "route_history": hist,
        "last_route_key": route_key,
        "routing_repeat_streak": streak,
        "specialist_route": route_key,
        "pending_audit_events": pending,
    }
    if loop:
        out["loop_detected"] = True
        out["status"] = "FAILED"
        out["error_message"] = "routing_loop_detected"
        pending.append(
            _audit_event(
                state,
                action="ROUTING_LOOP_ABORT",
                metadata={"route_key": route_key, "streak": streak},
            )
        )
        out["pending_audit_events"] = pending
    return out


async def fail_loop_node(state: OrchestratorState) -> dict[str, Any]:
    """Terminal node when routing safety triggers (checklist #37)."""
    logger.warning(
        "orchestrator_loop_fail",
        extra={
            "task_id": state.get("task_id"),
            "tenant_id": state.get("tenant_id"),
            "loop_detected": state.get("loop_detected"),
        },
    )
    return {"status": "FAILED"}


async def _call_openrouter_with_retry_fallback(
    *,
    openrouter: OpenRouterClient | None,
    settings: Settings,
    state: OrchestratorState,
    messages: list[dict[str, str]],
    primary_model: str,
    fallback_model: str,
    max_attempts: int,
) -> tuple[str, str, int, dict[str, Any]]:
    """
    Retry transient HTTP failures; fallback to cheaper model on exhaustion (checklist #31).

    Returns (content, model_used, tokens_added, raw_usage_dict).
    """
    tokens_used = int(state.get("tokens_used") or 0)
    budget = int(
        state.get("token_budget") or settings.orchestrator_token_budget_default
    )

    async def _chat(model: str) -> tuple[str, str, int, dict[str, Any]]:
        if openrouter is None:
            raise RuntimeError("openrouter_unavailable")
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(max(1, max_attempts)),
            wait=wait_exponential_jitter(initial=0.2, max=3.0),
            retry=retry_if_exception_type(_PRIMARY_RETRY_EXC),
            reraise=True,
        ):
            with attempt:
                result = await openrouter.chat_completion(
                    model=model,
                    messages=messages,
                    max_completion_tokens=min(
                        512, max(1, budget - tokens_used) if budget else 512
                    ),
                    langfuse_task_type="orchestrator_specialist",
                    langfuse_metadata={
                        "tenant_id": state.get("tenant_id"),
                        "task_id": state.get("task_id"),
                        "model": model,
                    },
                )
                add_toks = _usage_tokens(result.usage)
                meta = dict(result.usage) if isinstance(result.usage, dict) else {}
                return result.content, result.model, add_toks, meta
        raise RuntimeError("unreachable")

    chosen_primary = fallback_model if tokens_used >= budget else primary_model
    try:
        return await _chat(chosen_primary)
    except Exception as exc_primary:
        logger.warning(
            "orchestrator_primary_model_exhausted",
            extra={
                "task_id": state.get("task_id"),
                "error": str(exc_primary)[:500],
            },
        )
        return await _chat(fallback_model)


async def run_specialist_node(
    state: OrchestratorState,
    *,
    settings: Settings,
    openrouter: OpenRouterClient | None,
    session_factory: Any | None = None,
    weaviate_client: Any | None = None,
) -> dict[str, Any]:
    """Execute the routed specialist (stub / LLM) with tenant-scoped metadata (#34)."""
    route = state.get("specialist_route") or task_type_to_route(state["task_type"])
    step = int(state.get("step_count") or 0) + 1

    if route == ROUTE_DOCUMENT and session_factory is not None:
        async with session_factory() as session:
            doc_out = await run_documentation_specialist(
                session, state, settings, openrouter
            )
        if doc_out.get("status") == "FAILED" or doc_out.get("error_message"):
            return doc_out
        return doc_out

    if route == ROUTE_RCM and session_factory is not None:
        async with session_factory() as session:
            rcm_out = await run_rcm_specialist(
                session, state, settings, openrouter, weaviate_client
            )
        if rcm_out.get("status") == "FAILED" or rcm_out.get("error_message"):
            return rcm_out
        return rcm_out

    payload_preview = json.dumps(
        {
            "tenant_id": state.get("tenant_id"),
            "task_id": state.get("task_id"),
            "route": route,
        },
        sort_keys=True,
    )
    input_hash = hashlib.sha256(payload_preview.encode()).hexdigest()
    pending = list(state.get("pending_audit_events") or [])

    agent_outputs = dict(state.get("agent_outputs") or {})
    confidence_scores = dict(state.get("confidence_scores") or {})
    model_versions = dict(state.get("model_versions") or {})

    tokens_used = int(state.get("tokens_used") or 0)
    budget = int(
        state.get("token_budget") or settings.orchestrator_token_budget_default
    )

    summary_lines = [
        f"You are the HealthOS specialist for route {route}.",
        "Respond with one short JSON object only keys: summary (string), confidence (0-1 float).",
        f"TaskType={state.get('task_type')}. Tenant={state.get('tenant_id')}.",
    ]
    messages = [
        {"role": "system", "content": "You output compact JSON only."},
        {"role": "user", "content": "\n".join(summary_lines)},
    ]

    used_stub = False
    content = ""
    model_used = settings.orchestrator_llm_fallback_model

    if settings.resolved_openrouter_api_key and openrouter is not None:
        over_budget = tokens_used >= budget
        if over_budget:
            model_used = settings.orchestrator_llm_fallback_model
            model_versions["budget_downgrade"] = True
        try:
            content, model_used, add_toks, raw_usage = (
                await _call_openrouter_with_retry_fallback(
                    openrouter=openrouter,
                    settings=settings,
                    state=state,
                    messages=messages,
                    primary_model=(
                        settings.orchestrator_llm_fallback_model
                        if over_budget
                        else settings.orchestrator_llm_primary_model
                    ),
                    fallback_model=settings.orchestrator_llm_fallback_model,
                    max_attempts=settings.orchestrator_max_transient_retries,
                )
            )
            tokens_used = min(budget, tokens_used + add_toks)
            model_versions["specialist_usage_last"] = raw_usage
        except Exception as exc:
            logger.exception(
                "orchestrator_specialist_failed",
                extra={"task_id": state.get("task_id"), "route": route},
            )
            used_stub = True
            content = json.dumps(
                {
                    "summary": f"stub_specialist_error:{exc.__class__.__name__}",
                    "confidence": 0.75,
                }
            )
            model_versions["stub"] = True
    else:
        used_stub = True
        content = json.dumps(
            {
                "summary": f"stub_output:{route}",
                "confidence": 0.85,
            }
        )
        model_versions["stub"] = True

    try:
        parsed = json.loads(content)
        conf = float(parsed.get("confidence", 0.85))
    except (json.JSONDecodeError, TypeError, ValueError):
        conf = 0.75

    agent_outputs["specialist"] = {"route": route, "text": content, "stub": used_stub}
    confidence_scores["specialist"] = conf
    model_versions["specialist_model"] = model_used

    pending.append(
        _audit_event(
            state,
            action="SPECIALIST_COMPLETED",
            metadata={
                "route": route,
                "model_version": model_used,
                "confidence": conf,
                "input_hash": input_hash,
                "stub": used_stub,
            },
        )
    )

    return {
        "step_count": step,
        "agent_outputs": agent_outputs,
        "confidence_scores": confidence_scores,
        "model_versions": model_versions,
        "tokens_used": tokens_used,
        "input_hash": input_hash,
        "pending_audit_events": pending,
    }


async def maybe_hitl_node(state: OrchestratorState) -> dict[str, Any]:
    """Mark HITL requirement when confidence is below PRD threshold (0.8)."""
    if state.get("error_message") or state.get("status") == "FAILED":
        return {"hitl_required": False}
    scores = state.get("confidence_scores") or {}
    conf = float(scores.get("specialist", 1.0))
    required = conf < 0.8
    return {"hitl_required": required}


async def human_gate_node(state: OrchestratorState) -> dict[str, Any]:
    """
    Human-in-the-loop gate using LangGraph interrupt (#30).

    Resume with Command(resume={...}) from POST /tasks/{id}/approve.
    """
    if state.get("error_message") or state.get("status") == "FAILED":
        return {"status": "FAILED"}
    if not state.get("hitl_required"):
        return {"status": "SUCCEEDED"}

    resume_payload = interrupt(
        {"task_id": state.get("task_id"), "reason": "hitl_review_pending"}
    )
    pending = list(state.get("pending_audit_events") or [])
    approved = True
    override_notes: str | None = None
    if isinstance(resume_payload, dict):
        approved = bool(resume_payload.get("approved", True))
        override_notes = resume_payload.get("notes") if resume_payload else None
    pending.append(
        _audit_event(
            state,
            action="HITL_RESUME",
            metadata={
                "approved": approved,
                "human_override_notes": override_notes,
                "resume_payload_type": type(resume_payload).__name__,
            },
        )
    )
    outputs = dict(state.get("agent_outputs") or {})
    outputs["hitl"] = {"approved": approved, "notes": override_notes}
    status = "SUCCEEDED" if approved else "FAILED"
    return {
        "agent_outputs": outputs,
        "pending_audit_events": pending,
        "status": status,
    }


def route_after_route_task(state: OrchestratorState) -> str:
    return "fail_loop" if state.get("loop_detected") else "run_specialist"


def compile_specialist_node(
    settings: Settings,
    openrouter: OpenRouterClient | None,
    session_factory: Any | None = None,
    weaviate_client: Any | None = None,
):
    """
    Close over Settings + OpenRouter for tenant-scoped specialist execution (#34).
    """

    async def _specialist_wrapper(s: OrchestratorState) -> dict[str, Any]:
        return await run_specialist_node(
            s,
            settings=settings,
            openrouter=openrouter,
            session_factory=session_factory,
            weaviate_client=weaviate_client,
        )

    return _specialist_wrapper
