"""
FHIR DocumentReference write-back for approved clinical notes (Section D #45).

Creates versioned resources via ``relatesTo`` when a prior logical id exists (append-only chain).
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from typing import Any

from api.fhir.handlers.document_reference import DocumentReferenceFhirHandler
from api.fhir.mappers import validate_document_reference
from db.models.encounter import Encounter
from db.models.note import Note
from db.models.patient import Patient


def note_plain_text(note: Note) -> str:
    soap = note.soap or {}
    parts = [
        str(soap.get("subjective") or ""),
        str(soap.get("objective") or ""),
        str(soap.get("assessment") or ""),
        str(soap.get("plan") or ""),
    ]
    return "\n\n".join(p for p in parts if p).strip() or (note.content_text or "")


def build_document_reference_resource(
    *,
    note: Note,
    encounter: Encounter,
    patient: Patient,
) -> dict[str, Any]:
    """Minimal valid R4 DocumentReference for a clinical note body."""
    text = note_plain_text(note)
    raw = text.encode("utf-8")
    b64 = base64.standard_b64encode(raw).decode("ascii")
    title = note.title or "Clinical Note"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    patient_ref = patient.fhir_patient_id
    encounter_ref = encounter.fhir_encounter_id
    if not patient_ref or not encounter_ref:
        raise ValueError(
            "Patient and Encounter FHIR logical ids are required for write-back"
        )

    subject: dict[str, Any] = {"reference": f"Patient/{patient_ref}"}
    ctx: dict[str, Any] = {"encounter": [{"reference": f"Encounter/{encounter_ref}"}]}

    doc: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": "11506-3",
                    "display": "Progress note",
                }
            ]
        },
        "subject": subject,
        "date": now,
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain; charset=utf-8",
                    "data": b64,
                    "title": title[:200],
                    "creation": now,
                }
            }
        ],
    }
    if ctx:
        doc["context"] = ctx

    return validate_document_reference(doc)


async def publish_note_to_fhir(
    *,
    handler: DocumentReferenceFhirHandler,
    note: Note,
    encounter: Encounter,
    patient: Patient,
) -> dict[str, Any]:
    """
    POST new DocumentReference, or supersede when ``note.fhir_documentreference_id`` is set.
    """
    body = build_document_reference_resource(
        note=note, encounter=encounter, patient=patient
    )
    prev = note.fhir_documentreference_id
    if prev:
        return await handler.create_superseding_version(
            new_document=body,
            replaces_logical_id=prev,
        )
    return await handler.create_fhir(body)
