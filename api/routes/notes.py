"""
Clinical note review — POST /notes/{note_id}/approve (Section D #44, #45).

Edits are stored as structured diff metadata; approval triggers FHIR DocumentReference write-back.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import get_current_active_principal
from api.auth.principal import AuthPrincipal
from api.deps import get_db
from api.fhir.deps import get_document_reference_handler
from api.fhir.handlers.document_reference import DocumentReferenceFhirHandler
from api.services.fhir_document_writeback import publish_note_to_fhir
from db.base import utc_now
from db.enums import ActorType, NoteStatus, TaskStatus
from db.models.audit_trail import AuditTrail
from db.models.encounter import Encounter
from db.models.note import Note
from db.models.patient import Patient
from db.models.task import Task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notes", tags=["notes"])


class ApproveNoteBody(BaseModel):
    approved: bool = True
    #: Partial SOAP dict merged onto ``note.soap`` when approving (clinician edits).
    edited_soap: dict[str, Any] | None = None
    reviewer_notes: str | None = None


class NoteApprovalResponse(BaseModel):
    note_id: UUID
    status: NoteStatus
    fhir_documentreference_id: str | None = None
    fhir_warning: str | None = None


def _soap_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = set(before) | set(after)
    diff: dict[str, Any] = {}
    for k in keys:
        b, a = before.get(k), after.get(k)
        if b != a:
            diff[k] = {"before": b, "after": a}
    return diff


@router.post("/{note_id}/approve", response_model=NoteApprovalResponse)
async def approve_note(
    note_id: UUID,
    body: ApproveNoteBody,
    principal: Annotated[AuthPrincipal, Depends(get_current_active_principal)],
    db: Annotated[AsyncSession, Depends(get_db)],
    doc_handler: Annotated[
        DocumentReferenceFhirHandler, Depends(get_document_reference_handler)
    ],
) -> NoteApprovalResponse:
    res = await db.execute(
        select(Note).where(Note.id == note_id, Note.tenant_id == principal.tenant_id)
    )
    note = res.scalar_one_or_none()
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Note not found")

    if note.status == NoteStatus.APPROVED:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Note already approved")

    enc_res = await db.execute(
        select(Encounter).where(
            Encounter.id == note.encounter_id,
            Encounter.tenant_id == principal.tenant_id,
        )
    )
    encounter = enc_res.scalar_one_or_none()
    if encounter is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Encounter missing for note"
        )

    pat_res = await db.execute(
        select(Patient).where(
            Patient.id == encounter.patient_id,
            Patient.tenant_id == principal.tenant_id,
        )
    )
    patient = pat_res.scalar_one_or_none()
    if patient is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Patient not found")

    if not body.approved:
        prev_status = note.status
        note.status = NoteStatus.REJECTED
        vm = dict(note.validation_metadata or {})
        vm["review"] = {
            "approved": False,
            "reviewer_notes": body.reviewer_notes,
            "reviewer_user_id": str(principal.user_id),
            "reviewed_at": utc_now().isoformat(),
        }
        note.validation_metadata = vm
        note.updated_by = str(principal.user_id)

        if note.task_id:
            tres = await db.execute(select(Task).where(Task.id == note.task_id))
            t = tres.scalar_one_or_none()
            if t is not None:
                t.status = TaskStatus.FAILED
                t.error_message = "note_rejected_by_clinician"
                t.hitl_required = False

        db.add(
            AuditTrail(
                tenant_id=principal.tenant_id,
                task_id=note.task_id,
                actor_id=str(principal.user_id),
                actor_type=ActorType.USER,
                action="NOTE_REJECTED",
                resource_type="note",
                resource_id=str(note.id),
                before={"status": prev_status.value},
                after={"status": NoteStatus.REJECTED.value},
                event_metadata={
                    "notes": body.reviewer_notes,
                },
                created_at=utc_now(),
            )
        )
        await db.commit()
        await db.refresh(note)
        return NoteApprovalResponse(note_id=note.id, status=note.status)

    before_soap = dict(note.soap or {})
    merged = dict(before_soap)
    if body.edited_soap:
        merged.update(body.edited_soap)

    vm = dict(note.validation_metadata or {})
    if body.edited_soap:
        vm["approval_diff"] = _soap_diff(before_soap, merged)
    vm["review"] = {
        "approved": True,
        "reviewer_notes": body.reviewer_notes,
        "reviewer_user_id": str(principal.user_id),
        "reviewed_at": utc_now().isoformat(),
    }

    note.soap = merged
    note.content_text = "\n\n".join(
        [
            str(merged.get("subjective") or ""),
            str(merged.get("objective") or ""),
            str(merged.get("assessment") or ""),
            str(merged.get("plan") or ""),
        ]
    )
    note.validation_metadata = vm
    note.status = NoteStatus.APPROVED
    note.reviewed_at = datetime.now(timezone.utc)
    note.approved_at = datetime.now(timezone.utc)
    note.updated_by = str(principal.user_id)

    fhir_id: str | None = None
    warn: str | None = None
    if not patient.fhir_patient_id or not encounter.fhir_encounter_id:
        warn = (
            "FHIR sync skipped: patient.fhir_patient_id and encounter.fhir_encounter_id "
            "must be set for DocumentReference write-back."
        )
        logger.warning(
            "fhir_write_skipped_missing_refs", extra={"note_id": str(note.id)}
        )
    else:
        try:
            created = await publish_note_to_fhir(
                handler=doc_handler,
                note=note,
                encounter=encounter,
                patient=patient,
            )
            fhir_id = str(created.get("id") or "")
            if fhir_id:
                note.fhir_documentreference_id = fhir_id
        except Exception as exc:
            warn = f"FHIR write failed: {str(exc)[:500] or exc.__class__.__name__}"
            logger.exception("fhir_documentreference_write_failed")

    db.add(
        AuditTrail(
            tenant_id=principal.tenant_id,
            task_id=note.task_id,
            actor_id=str(principal.user_id),
            actor_type=ActorType.USER,
            action="NOTE_APPROVED",
            resource_type="note",
            resource_id=str(note.id),
            before={"status": NoteStatus.IN_REVIEW.value},
            after={
                "status": NoteStatus.APPROVED.value,
                "fhir_documentreference_id": note.fhir_documentreference_id,
            },
            event_metadata={
                "reviewer_notes": body.reviewer_notes,
                "fhir_warning": warn,
            },
            created_at=utc_now(),
        )
    )

    await db.commit()
    await db.refresh(note)

    return NoteApprovalResponse(
        note_id=note.id,
        status=note.status,
        fhir_documentreference_id=note.fhir_documentreference_id,
        fhir_warning=warn,
    )
