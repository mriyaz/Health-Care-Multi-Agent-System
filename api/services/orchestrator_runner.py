"""Run orchestrator graphs against persisted Task rows (Section C)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.settings import Settings
from db.base import utc_now
from db.enums import ActorType, HITLStatus, TaskStatus
from db.models.audit_trail import AuditTrail
from db.models.task import Task

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _initial_graph_input(task: Task, settings: Settings) -> dict[str, Any]:
    doc_intake: dict[str, Any] = {}
    rcm_intake: dict[str, Any] = {}
    st = task.agent_state or {}
    if isinstance(st, dict):
        raw = st.get("document_intake")
        if isinstance(raw, dict):
            doc_intake = raw
        raw_r = st.get("rcm_intake")
        if isinstance(raw_r, dict):
            rcm_intake = raw_r
    return {
        "task_id": str(task.id),
        "task_type": task.task_type.value,
        "tenant_id": str(task.tenant_id),
        "patient_id": str(task.patient_id) if task.patient_id else None,
        "encounter_id": str(task.encounter_id) if task.encounter_id else None,
        "status": "RUNNING",
        "agent_outputs": dict(task.agent_outputs or {}),
        "confidence_scores": dict(task.confidence_scores or {}),
        "model_versions": dict(task.model_metadata or {}),
        "hitl_required": bool(task.hitl_required),
        "tokens_used": 0,
        "token_budget": settings.orchestrator_token_budget_default,
        "route_history": [],
        "last_route_key": None,
        "routing_repeat_streak": 0,
        "loop_detected": False,
        "step_count": 0,
        "transient_retries": 0,
        "input_hash": task.input_hash,
        "error_message": None,
        "pending_audit_events": [],
        "specialist_route": "",
        "document_intake": doc_intake,
        "rcm_intake": rcm_intake,
    }


async def _append_audit_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    task_id: UUID,
    actor_id: str | None,
    actor_type: ActorType,
    events: list[dict[str, Any]],
) -> None:
    created = utc_now()
    for ev in events:
        meta = ev.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
        session.add(
            AuditTrail(
                tenant_id=tenant_id,
                task_id=task_id,
                actor_id=actor_id,
                actor_type=actor_type,
                action=str(ev.get("action") or "ORCHESTRATOR_EVENT"),
                resource_type="task",
                resource_id=str(task_id),
                before=None,
                after=None,
                event_metadata=meta,
                created_at=created,
            )
        )


class OrchestratorRunner:
    """
    Executes the compiled LangGraph with Postgres checkpoints and syncs the Task ORM row.
    """

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        graph: Any,
    ) -> None:
        self._session = session
        self._settings = settings
        self._graph = graph

    async def _load_task(self, task_id: UUID, tenant_id: UUID) -> Task:
        res = await self._session.execute(
            select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id)
        )
        task = res.scalar_one_or_none()
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
            )
        return task

    async def execute(
        self,
        *,
        task_id: UUID,
        tenant_id: UUID,
        resume: dict[str, Any] | None,
        actor_user_id: UUID | None,
    ) -> dict[str, Any]:
        task = await self._load_task(task_id, tenant_id)
        config: dict[str, Any] = {"configurable": {"thread_id": str(task_id)}}

        if resume is not None:
            if task.status != TaskStatus.BLOCKED or not task.hitl_required:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Task is not awaiting HITL approval",
                )
            task.hitl_status = HITLStatus.IN_REVIEW
            graph_input: Any = Command(resume=resume)
        else:
            if task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Task is not runnable from this state",
                )
            task.status = TaskStatus.RUNNING
            if task.started_at is None:
                task.started_at = _now()
            graph_input = _initial_graph_input(task, self._settings)

        result = await self._graph.ainvoke(graph_input, config)

        interrupt = result.get("__interrupt__")
        if interrupt:
            task.status = TaskStatus.BLOCKED
            task.hitl_required = True
            task.hitl_status = HITLStatus.REQUIRED
        else:
            out_status = str(result.get("status") or "SUCCEEDED")
            if result.get("loop_detected"):
                task.status = TaskStatus.FAILED
                task.error_message = result.get("error_message") or "routing_loop"
                task.hitl_required = False
                task.hitl_status = HITLStatus.NOT_REQUIRED
                logger.error(
                    "orchestrator_routing_loop",
                    extra={
                        "task_id": str(task.id),
                        "tenant_id": str(task.tenant_id),
                    },
                )
            elif out_status == "FAILED":
                task.status = TaskStatus.FAILED
                task.hitl_required = False
                ho = (result.get("agent_outputs") or {}).get("hitl")
                if isinstance(ho, dict) and ho.get("approved") is False:
                    task.hitl_status = HITLStatus.REJECTED
                    task.error_message = str(ho.get("notes") or "hitl_rejected")
                else:
                    task.hitl_status = HITLStatus.NOT_REQUIRED
                    task.error_message = result.get("error_message") or "task_failed"
            elif out_status == "SUCCEEDED":
                task.status = TaskStatus.SUCCEEDED
                task.completed_at = _now()
                task.hitl_required = False
                ho = (result.get("agent_outputs") or {}).get("hitl")
                if isinstance(ho, dict):
                    task.hitl_status = (
                        HITLStatus.APPROVED
                        if ho.get("approved", True)
                        else HITLStatus.REJECTED
                    )
                else:
                    task.hitl_status = HITLStatus.NOT_REQUIRED
            else:
                task.status = TaskStatus.FAILED
                task.hitl_required = False
                task.error_message = out_status

        # Persist orchestrator snapshot fields
        clean = {k: v for k, v in result.items() if k != "__interrupt__"}
        task.agent_state = clean
        task.agent_outputs = dict(result.get("agent_outputs") or {})
        task.confidence_scores = dict(result.get("confidence_scores") or {})
        task.model_metadata = dict(result.get("model_versions") or {})
        task.input_hash = result.get("input_hash") or task.input_hash

        pending = list(result.get("pending_audit_events") or [])
        if pending:
            await _append_audit_events(
                self._session,
                tenant_id=tenant_id,
                task_id=task.id,
                actor_id=str(actor_user_id) if actor_user_id else None,
                actor_type=ActorType.USER if actor_user_id else ActorType.SYSTEM,
                events=pending,
            )

        return result
