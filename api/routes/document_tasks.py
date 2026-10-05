"""
Clinical Documentation intake — POST /tasks/document (Section D #38).

Creates a ``DOCUMENT`` orchestrator task with structured ``agent_state.document_intake``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
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

router = APIRouter(prefix="/tasks", tags=["documentation"])

_ALLOWED_AUDIO_CT = frozenset(
    {
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/mp4",
        "audio/x-m4a",
        "audio/m4a",
        None,
    }
)
_ALLOWED_EXT = frozenset({".mp3", ".wav", ".m4a"})


@router.post("/document", response_model=CreateTaskResponse)
async def create_document_task(
    request: Request,
    background_tasks: BackgroundTasks,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    encounter_id: Annotated[UUID, Form()],
    transcript: Annotated[str | None, Form()] = None,
    note_kind: Annotated[str, Form()] = "soap",
    specialty: Annotated[str, Form()] = "GENERAL",
    priority: Annotated[Priority, Form()] = Priority.NORMAL,
    patient_id: Annotated[UUID | None, Form()] = None,
    extra_context_json: Annotated[str | None, Form()] = None,
    audio: UploadFile | None = File(None),
) -> CreateTaskResponse:
    """
    Accept audio (mp3/wav/m4a) **or** plain-text transcript; validates size/type (#38).

    Persists intake on the Task row under ``agent_state.document_intake`` and enqueues
    the orchestrator (Whisper runs inside the graph when audio is supplied).
    """
    settings = request.app.state.settings
    max_bytes = max(1, settings.documentation_max_upload_mb) * 1024 * 1024

    res = await db.execute(
        select(Encounter).where(
            Encounter.id == encounter_id,
            Encounter.tenant_id == principal.tenant_id,
        )
    )
    enc = res.scalar_one_or_none()
    if enc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Encounter not found")

    resolved_patient = patient_id or enc.patient_id

    audio_path: str | None = None
    audio_name: str | None = None

    if audio is not None and audio.filename:
        suffix = Path(audio.filename).suffix.lower()
        if suffix not in _ALLOWED_EXT:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported audio extension {suffix!r}; use mp3, wav, or m4a.",
            )
        ct = audio.content_type
        if ct not in _ALLOWED_AUDIO_CT:
            logger.warning("audio_content_type_unusual", extra={"content_type": ct})

        fd, tmp_path = tempfile.mkstemp(
            suffix=suffix, prefix="healthos_doc_", dir=tempfile.gettempdir()
        )
        os.close(fd)
        total = 0
        try:
            while True:
                chunk = await audio.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Audio exceeds configured DOCUMENTATION_MAX_UPLOAD_MB",
                    )
                with open(tmp_path, "ab") as out:
                    out.write(chunk)
        except HTTPException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

        audio_path = tmp_path
        audio_name = audio.filename

    tr = (transcript or "").strip()
    if not tr and not audio_path:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Provide either `transcript` text or an audio file.",
        )
    if tr and audio_path:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="Send transcript **or** audio, not both.",
        )

    if len(tr.encode("utf-8")) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Transcript exceeds configured DOCUMENTATION_MAX_UPLOAD_MB",
        )

    extra: dict[str, Any] = {}
    if extra_context_json:
        try:
            parsed = json.loads(extra_context_json)
            if isinstance(parsed, dict):
                extra = parsed
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                detail=f"extra_context_json must be JSON object: {exc}",
            ) from exc

    nk = (note_kind or "soap").lower().strip()
    if nk not in ("soap", "discharge_summary", "referral"):
        nk = "soap"

    intake = {
        "transcript": tr if tr else None,
        "audio_path": audio_path,
        "audio_filename": audio_name,
        "note_kind": nk,
        "specialty": (specialty or "GENERAL").upper(),
        "extra_context": extra,
    }

    task = Task(
        id=uuid4(),
        tenant_id=principal.tenant_id,
        task_type=TaskType.DOCUMENT,
        status=TaskStatus.QUEUED,
        priority=priority,
        patient_id=resolved_patient,
        encounter_id=encounter_id,
        agent_state={"document_intake": intake},
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
