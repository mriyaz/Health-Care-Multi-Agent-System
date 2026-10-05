"""
Orchestrator task API (Section C — checklist #32, #30 approve).

- ``POST /tasks`` — enqueue work for the orchestrator graph.
- ``GET /tasks/{task_id}`` and ``GET /tasks/{task_id}/status`` — poll durable status.
- ``POST /tasks/{task_id}/approve`` — resume LangGraph after ``interrupt()`` HITL.
- ``GET /tasks`` — tenant-scoped listing with priority ordering (#36).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import get_current_active_principal
from api.auth.principal import AuthPrincipal
from api.deps import get_db
from api.services.orchestrator_runner import OrchestratorRunner
from db.enums import Priority, TaskStatus, TaskType
from db.models.task import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


class CreateTaskBody(BaseModel):
    task_type: TaskType
    patient_id: UUID | None = None
    encounter_id: UUID | None = None
    priority: Priority = Priority.NORMAL


class CreateTaskResponse(BaseModel):
    task_id: UUID


class ApproveBody(BaseModel):
    approved: bool = True
    notes: str | None = None


class TaskStatusResponse(BaseModel):
    task_id: UUID
    tenant_id: UUID
    task_type: TaskType
    status: TaskStatus
    priority: Priority
    patient_id: UUID | None
    encounter_id: UUID | None
    hitl_required: bool
    hitl_pending: bool
    agent_outputs: dict[str, Any]
    confidence_scores: dict[str, Any]
    model_versions: dict[str, Any]
    input_hash: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


async def _run_orchestrator_background(
    app: Any,
    task_id: UUID,
    tenant_id: UUID,
    actor_user_id: UUID,
) -> None:
    settings = app.state.settings
    graph = app.state.orchestrator_graph
    factory = app.state.session_factory
    try:
        async with factory() as session:
            runner = OrchestratorRunner(session, settings, graph)
            await runner.execute(
                task_id=task_id,
                tenant_id=tenant_id,
                resume=None,
                actor_user_id=actor_user_id,
            )
            await session.commit()
    except Exception as exc:
        logger.exception(
            "orchestrator_background_failed",
            extra={"task_id": str(task_id), "tenant_id": str(tenant_id)},
        )
        async with factory() as session:
            res = await session.execute(
                select(Task).where(Task.id == task_id, Task.tenant_id == tenant_id)
            )
            task = res.scalar_one_or_none()
            if task is not None and task.status in (
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
                TaskStatus.BLOCKED,
            ):
                task.status = TaskStatus.FAILED
                task.error_message = str(exc)[:2000]
                task.updated_by = str(actor_user_id)
                await session.commit()


def _to_response(row: Task) -> TaskStatusResponse:
    hitl_pending = row.status == TaskStatus.BLOCKED and row.hitl_required
    meta = dict(row.model_metadata or {})
    return TaskStatusResponse(
        task_id=row.id,
        tenant_id=row.tenant_id,
        task_type=row.task_type,
        status=row.status,
        priority=row.priority,
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        hitl_required=row.hitl_required,
        hitl_pending=hitl_pending,
        agent_outputs=dict(row.agent_outputs or {}),
        confidence_scores=dict(row.confidence_scores or {}),
        model_versions=meta,
        input_hash=row.input_hash,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


@router.post("", response_model=CreateTaskResponse)
async def create_task(
    request: Request,
    body: CreateTaskBody,
    background_tasks: BackgroundTasks,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CreateTaskResponse:
    task = Task(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        task_type=body.task_type,
        status=TaskStatus.QUEUED,
        priority=body.priority,
        patient_id=body.patient_id,
        encounter_id=body.encounter_id,
        created_by=str(principal.user_id),
        updated_by=str(principal.user_id),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    background_tasks.add_task(
        _run_orchestrator_background,
        request.app,
        task.id,
        principal.tenant_id,
        principal.user_id,
    )
    return CreateTaskResponse(task_id=task.id)


@router.get("", response_model=list[TaskStatusResponse])
async def list_tasks(
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    task_status: TaskStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
) -> list[TaskStatusResponse]:
    """Queued tasks surface first by priority (URGENT → LOW) for operator queues (#36)."""
    prio_rank = case(
        (Task.priority == Priority.URGENT, 0),
        (Task.priority == Priority.HIGH, 1),
        (Task.priority == Priority.NORMAL, 2),
        (Task.priority == Priority.LOW, 3),
        else_=4,
    )
    stmt = select(Task).where(Task.tenant_id == principal.tenant_id)
    if task_status is not None:
        stmt = stmt.where(Task.status == task_status)
    stmt = stmt.order_by(prio_rank, Task.created_at.asc()).limit(limit)
    res = await db.execute(stmt)
    rows = res.scalars().all()
    return [_to_response(r) for r in rows]


@router.get("/{task_id}", response_model=TaskStatusResponse)
@router.get("/{task_id}/status", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: UUID,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TaskStatusResponse:
    res = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == principal.tenant_id)
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return _to_response(row)


@router.post("/{task_id}/approve", response_model=TaskStatusResponse)
async def approve_task(
    task_id: UUID,
    body: ApproveBody,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> TaskStatusResponse:
    settings = request.app.state.settings
    graph = request.app.state.orchestrator_graph
    runner = OrchestratorRunner(db, settings, graph)
    resume = {"approved": body.approved, "notes": body.notes}
    await runner.execute(
        task_id=task_id,
        tenant_id=principal.tenant_id,
        resume=resume,
        actor_user_id=principal.user_id,
    )
    await db.commit()
    res = await db.execute(
        select(Task).where(Task.id == task_id, Task.tenant_id == principal.tenant_id)
    )
    row = res.scalar_one()
    return _to_response(row)
