"""
HL7 v2 ↔ FHIR bridge (Checklist #26, P2 — interface + minimal parsing).

Production bidirectional conversion belongs in a dedicated MLLP / interface engine.
This module documents the seam and parses a few PID fields for teaching / smoke tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ParsedPid:
    """Subset of PID-5 / PID-7 / PID-11 for demo mapping."""

    family_name: Optional[str]
    given_name: Optional[str]
    birth_date: Optional[str]  # YYYYMMDD from HL7 v2
    address_line: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip_code: Optional[str]


def split_hl7_segments(message: str) -> list[str]:
    """Split on CR per HL7 framing (ignore MSH for this minimal parser)."""
    text = message.replace("\r\n", "\r").replace("\n", "\r")
    return [s for s in text.split("\r") if s.strip()]


def parse_pid_segment(pid: str) -> ParsedPid:
    """
    Parse pipe-delimited PID where fields are ``|`` separated (field 1 = PID).
    """
    fields = pid.split("|")
    # PID|1|... — index 5 = patient name, 7 = DOB, 11 = address
    fn, gn = None, None
    if len(fields) > 5 and fields[5]:
        parts = fields[5].split("^")
        if len(parts) >= 1:
            fn = parts[0] or None
        if len(parts) >= 2:
            gn = parts[1] or None
    dob_raw = fields[7] if len(fields) > 7 else None
    dob = None
    if dob_raw and len(dob_raw.strip()) >= 8:
        dob = dob_raw.strip()[:8]

    line = city = state = z = None
    if len(fields) > 11 and fields[11]:
        ap = fields[11].split("^")
        if len(ap) >= 1:
            line = ap[0] or None
        if len(ap) >= 3:
            city = ap[2] or None
        if len(ap) >= 4:
            state = ap[3] or None
        if len(ap) >= 5:
            z = ap[4] or None

    return ParsedPid(
        family_name=fn,
        given_name=gn,
        birth_date=dob,
        address_line=line,
        city=city,
        state=state,
        zip_code=z,
    )


def pid_to_fhir_patient_draft(
    pid: ParsedPid, *, patient_id: str = "hl7-derived-001"
) -> dict[str, Any]:
    """
    Build a minimal FHIR Patient from ``ParsedPid`` (not a full ADT mapper).
    """
    birth_iso: Optional[str] = None
    if pid.birth_date and re.fullmatch(r"\d{8}", pid.birth_date):
        birth_iso = f"{pid.birth_date[:4]}-{pid.birth_date[4:6]}-{pid.birth_date[6:8]}"
    addr = {}
    if pid.address_line or pid.city:
        addr = {
            "use": "home",
            "line": [pid.address_line] if pid.address_line else [],
            "city": pid.city or "",
            "state": pid.state or "",
            "postalCode": pid.zip_code or "",
            "country": "US",
        }
    pat: dict[str, Any] = {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [
            {"system": "urn:healthos:hl7v2:pid", "value": "derived-from-v2-message"}
        ],
        "active": True,
        "name": [
            {
                "family": pid.family_name or "Unknown",
                "given": [pid.given_name or "Unknown"],
            }
        ],
    }
    if birth_iso:
        pat["birthDate"] = birth_iso
    if addr:
        pat["address"] = [addr]
    return pat


def adt_message_to_fhir_bundle_placeholder(_message: str) -> dict[str, Any]:
    """
    Reserved for full ADT^A01 → FHIR Bundle conversion (P2).

    Raises ``NotImplementedError`` so callers detect incomplete deployments early.
    """
    raise NotImplementedError(
        "Full HL7 v2 ADT → FHIR Bundle conversion is deferred to P2 (Section B #26)."
    )
