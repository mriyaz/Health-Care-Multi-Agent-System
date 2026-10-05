"""
Revenue Cycle coding audit intake — ``POST /tasks/code-audit`` (Section E, checklist #91).

Creates a ``CODE_AUDIT`` / ``RCM_AUDIT`` orchestrator task with ``agent_state.rcm_intake``.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import get_current_active_principal
from api.auth.principal import AuthPrincipal
from api.deps import get_db
from api.routes.tasks import CreateTaskResponse, _run_orchestrator_background
from db.enums import Priority, TaskStatus, TaskType
from db.models.encounter import Encounter
from db.models.task import Task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["rcm"])


@router.post("/code-audit", response_model=CreateTaskResponse)
async def create_code_audit_task(
    request: Request,
    background_tasks: BackgroundTasks,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    encounter_id: Annotated[UUID, Form()],
    clinical_note_text: Annotated[str, Form()],
    specialty: Annotated[str, Form()] = "GENERAL",
    payer_org_identifier: Annotated[str, Form()] = "UNKNOWN_PAYER",
    procedure_description: Annotated[str | None, Form()] = None,
    existing_icd10_json: Annotated[str | None, Form()] = None,
    existing_cpt_json: Annotated[str | None, Form()] = None,
    priority: Annotated[Priority, Form()] = Priority.NORMAL,
    task_type: Annotated[TaskType, Form()] = TaskType.CODE_AUDIT,
) -> CreateTaskResponse:
    """
    Enqueue an async RCM coding audit (ICD/CPT suggest → validate → pre-bill → denial risk).

    Default ``task_type`` is ``CODE_AUDIT`` (alias of the RCM specialist). Use
    ``RCM_AUDIT`` if you prefer the explicit enum name.
    """
    if task_type not in (TaskType.CODE_AUDIT, TaskType.RCM_AUDIT):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="task_type must be CODE_AUDIT or RCM_AUDIT",
        )

    res = await db.execute(
        select(Encounter).where(
            Encounter.id == encounter_id,
            Encounter.tenant_id == principal.tenant_id,
        )
    )
    enc = res.scalar_one_or_none()
    if enc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Encounter not found")

    note = clinical_note_text.strip()
    if not note:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="clinical_note_text is required",
        )

    existing_icd: list[str] | None = None
    existing_cpt: list[str] | None = None
    if existing_icd10_json:
        try:
            parsed = json.loads(existing_icd10_json)
            if isinstance(parsed, list):
                existing_icd = [str(x) for x in parsed]
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"existing_icd10_json must be a JSON array: {exc}",
            ) from exc
    if existing_cpt_json:
        try:
            parsed = json.loads(existing_cpt_json)
            if isinstance(parsed, list):
                existing_cpt = [str(x) for x in parsed]
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"existing_cpt_json must be a JSON array: {exc}",
            ) from exc

    intake: dict[str, Any] = {
        "clinical_note_text": note,
        "specialty": (specialty or "GENERAL").upper(),
        "payer_org_identifier": (payer_org_identifier or "UNKNOWN_PAYER").strip(),
        "procedure_description": (procedure_description or "").strip() or None,
        "existing_icd10": existing_icd,
        "existing_cpt": existing_cpt,
    }

    task = Task(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        task_type=task_type,
        status=TaskStatus.QUEUED,
        priority=priority,
        patient_id=enc.patient_id,
        encounter_id=encounter_id,
        agent_state={"rcm_intake": intake},
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
