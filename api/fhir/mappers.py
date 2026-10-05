"""
Map between FHIR R4 JSON dicts and HealthOS persistence fields.

Validation uses ``fhir.resources`` where models exist; unknown extensions are preserved in JSON.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Optional

from fhir.resources.condition import Condition as FhirCondition
from fhir.resources.documentreference import DocumentReference as FhirDocumentReference
from fhir.resources.encounter import Encounter as FhirEncounter
from fhir.resources.medicationrequest import MedicationRequest as FhirMedicationRequest
from fhir.resources.observation import Observation as FhirObservation
from fhir.resources.patient import Patient as FhirPatient
from fhir.resources.servicerequest import ServiceRequest as FhirServiceRequest

from db.enums import EncounterStatus


def _one_line_address(addr: dict[str, Any]) -> str:
    line = " ".join(addr.get("line") or [])
    city = (addr.get("city") or "").strip()
    state = (addr.get("state") or "").strip()
    pc = (addr.get("postalCode") or "").strip()
    country = (addr.get("country") or "").strip()
    parts = [line, city, state, pc, country]
    return "|".join(p.lower().strip() for p in parts if p)


def patient_address_from_fhir(patient: dict[str, Any]) -> Optional[dict[str, Any]]:
    addrs = patient.get("address") or []
    for a in addrs:
        if isinstance(a, dict) and a.get("use") in (None, "home", "work"):
            return a
    if addrs and isinstance(addrs[0], dict):
        return addrs[0]
    return None


def patient_dedup_fingerprint(patient: dict[str, Any]) -> str:
    """
    Stable fingerprint for name + DOB + address (Checklist #16 deduplication).
    """
    names = patient.get("name") or []
    family = ""
    given = ""
    if names and isinstance(names[0], dict):
        family = (names[0].get("family") or "").strip().lower()
        given_list = names[0].get("given") or []
        if given_list:
            given = str(given_list[0]).strip().lower()
    dob = (patient.get("birthDate") or "").strip()
    addr = patient_address_from_fhir(patient) or {}
    addr_s = _one_line_address(addr)
    raw = json.dumps(
        {"given": given, "family": family, "dob": dob, "addr": addr_s},
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def patient_to_internal_fields(
    patient: dict[str, Any],
) -> dict[str, Any]:
    """Fields for ``db.models.patient.Patient`` (not including tenant / actor)."""
    names = patient.get("name") or []
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    if names and isinstance(names[0], dict):
        last_name = names[0].get("family")
        gl = names[0].get("given") or []
        if gl:
            first_name = str(gl[0])
    dob: Optional[date] = None
    if patient.get("birthDate"):
        try:
            dob = date.fromisoformat(str(patient["birthDate"])[:10])
        except ValueError:
            dob = None
    mrn = None
    for ident in patient.get("identifier") or []:
        if not isinstance(ident, dict):
            continue
        if ident.get("value"):
            mrn = str(ident["value"])
            break
    if not mrn:
        rid = patient.get("id") or "unknown"
        mrn = f"FHIR-{rid}"
    addr = patient_address_from_fhir(patient)
    meta = {
        "fhir_dedup_fingerprint": patient_dedup_fingerprint(patient),
        "fhir_address": addr,
    }
    return {
        "mrn": mrn[:64],
        "fhir_patient_id": str(patient.get("id") or "")[:128] or None,
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": dob,
        "patient_metadata": meta,
    }


def fhir_encounter_status_to_internal(status: Optional[str]) -> EncounterStatus:
    s = (status or "unknown").lower()
    if s in ("finished",):
        return EncounterStatus.FINISHED
    if s in ("cancelled",):
        return EncounterStatus.CANCELLED
    if s in ("in-progress", "onleave", "arrived", "triaged"):
        return EncounterStatus.IN_PROGRESS
    return EncounterStatus.PLANNED


def encounter_to_internal_metadata(enc: dict[str, Any]) -> dict[str, Any]:
    types = enc.get("type") or []
    type_text = None
    if types and isinstance(types[0], dict):
        type_text = types[0].get("text")
    reason_text = _encounter_reason_text(enc)
    period = enc.get("actualPeriod") or enc.get("period") or {}
    return {
        "fhir_encounter_class": enc.get("class"),
        "fhir_type_text": type_text,
        "fhir_reason_text": reason_text,
        "fhir_period": period,
    }


def _encounter_reason_text(enc: dict[str, Any]) -> Optional[str]:
    """Extract human-readable reason from R4 ``reasonCode`` or R5 ``reason``."""
    legacy = enc.get("reasonCode") or []
    if legacy and isinstance(legacy[0], dict):
        text = legacy[0].get("text")
        if text:
            return str(text)
    for entry in enc.get("reason") or []:
        if not isinstance(entry, dict):
            continue
        for value in entry.get("value") or []:
            if not isinstance(value, dict):
                continue
            concept = value.get("concept") or {}
            if isinstance(concept, dict) and concept.get("text"):
                return str(concept["text"])
    return None


def encounter_period_to_datetimes(
    enc: dict[str, Any],
) -> tuple[Optional[datetime], Optional[datetime]]:
    period = enc.get("actualPeriod") or enc.get("period") or {}
    start_s = period.get("start")
    end_s = period.get("end")

    def parse_iso(s: Any) -> Optional[datetime]:
        if not s or not isinstance(s, str):
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None

    return parse_iso(start_s), parse_iso(end_s)


def _normalize_encounter_r4(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Coerce FHIR R4 Encounter JSON from HAPI into shapes ``fhir.resources`` 7 (R5) accepts.

    HealthOS targets HL7 R4 at the wire; the pinned ``fhir.resources`` major version validates
    against R5 element names (``actualPeriod``, ``reason``, list-valued ``class``).
    """
    enc = dict(resource)

    cls = enc.get("class")
    if cls is not None and not isinstance(cls, list):
        if isinstance(cls, dict) and cls.get("coding"):
            enc["class"] = [cls]
        elif isinstance(cls, dict):
            enc["class"] = [{"coding": [cls]}]
        else:
            enc["class"] = [cls]

    if "actualPeriod" not in enc and "period" in enc:
        enc["actualPeriod"] = enc.pop("period")

    if "reason" not in enc and enc.get("reasonCode"):
        reasons: list[dict[str, Any]] = []
        for item in enc.get("reasonCode") or []:
            if not isinstance(item, dict):
                continue
            concept: dict[str, Any] = {}
            if item.get("text"):
                concept["text"] = item["text"]
            coding = item.get("coding")
            if coding:
                concept["coding"] = coding
            if concept:
                reasons.append({"value": [{"concept": concept}]})
        if reasons:
            enc["reason"] = reasons
        enc.pop("reasonCode", None)

    return enc


def validate_patient(resource: dict[str, Any]) -> dict[str, Any]:
    model = FhirPatient.parse_obj(resource)
    return json.loads(model.json())


def validate_encounter(resource: dict[str, Any]) -> dict[str, Any]:
    model = FhirEncounter.parse_obj(_normalize_encounter_r4(resource))
    return json.loads(model.json())


def validate_condition(resource: dict[str, Any]) -> dict[str, Any]:
    model = FhirCondition.parse_obj(resource)
    return json.loads(model.json())


def _normalize_document_reference_r4(resource: dict[str, Any]) -> dict[str, Any]:
    """
    Coerce FHIR R4 DocumentReference JSON into shapes ``fhir.resources`` 7 (R5) accepts.

    R4 ``context`` is an object with ``encounter`` references; R5 uses a list of Reference.
    R4 ``relatesTo.code`` is often a plain code string; R5 expects CodeableConcept.
    """
    doc = dict(resource)

    ctx = doc.get("context")
    if isinstance(ctx, dict):
        refs: list[dict[str, Any]] = []
        for key in ("encounter", "patient", "related"):
            items = ctx.get(key) or []
            if isinstance(items, dict):
                items = [items]
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and item.get("reference"):
                    refs.append({"reference": str(item["reference"])})
        if refs:
            doc["context"] = refs
        else:
            doc.pop("context", None)

    relates = doc.get("relatesTo")
    if isinstance(relates, list):
        normalized_rel: list[dict[str, Any]] = []
        for rel in relates:
            if not isinstance(rel, dict):
                continue
            entry = dict(rel)
            code = entry.get("code")
            if isinstance(code, str):
                entry["code"] = {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/document-relationship-type",
                            "code": code,
                        }
                    ]
                }
            normalized_rel.append(entry)
        doc["relatesTo"] = normalized_rel

    return doc


def validate_document_reference(resource: dict[str, Any]) -> dict[str, Any]:
    model = FhirDocumentReference.parse_obj(_normalize_document_reference_r4(resource))
    return json.loads(model.json())


def validate_observation(resource: dict[str, Any]) -> dict[str, Any]:
    model = FhirObservation.parse_obj(resource)
    return json.loads(model.json())


def validate_medication_request(resource: dict[str, Any]) -> dict[str, Any]:
    model = FhirMedicationRequest.parse_obj(resource)
    return json.loads(model.json())


def validate_service_request(resource: dict[str, Any]) -> dict[str, Any]:
    model = FhirServiceRequest.parse_obj(resource)
    return json.loads(model.json())


def document_reference_with_replaces(
    new_doc: dict[str, Any],
    *,
    replaces_id: str,
    replaces_type: str = "DocumentReference",
) -> dict[str, Any]:
    """Append-only chain via ``relatesTo`` (Checklist #19)."""
    doc = dict(new_doc)
    rel = doc.get("relatesTo") or []
    rel = list(rel)
    rel.append(
        {
            "code": {
                "coding": [
                    {
                        "system": "http://hl7.org/fhir/document-relationship-type",
                        "code": "replaces",
                    }
                ]
            },
            "target": {"reference": f"{replaces_type}/{replaces_id}"},
        }
    )
    doc["relatesTo"] = rel
    return doc


def enforce_medication_request_draft_safe(resource: dict[str, Any]) -> dict[str, Any]:
    """
    P1 safety: only draft / proposal-like MedicationRequest writes from HealthOS.
    """
    mr = dict(resource)
    mr["status"] = "draft"
    mr["intent"] = mr.get("intent") or "proposal"
    return validate_medication_request(mr)
