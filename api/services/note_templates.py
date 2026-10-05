"""
Per-specialty documentation prompts (Section D #48 — templates, tenant-aware via intake).

Templates adjust system instructions only; SOAP/discharge/referral JSON schema stays stable.
"""

from __future__ import annotations

from typing import Literal

DocumentationSpecialty = Literal[
    "GENERAL",
    "GP",
    "CARDIOLOGY",
    "MENTAL_HEALTH",
    "AGED_CARE",
]


def specialty_system_addon(specialty: str) -> str:
    key = (specialty or "GENERAL").upper().replace("-", "_")
    addons = {
        "GENERAL": "Use standard outpatient clinical language.",
        "GP": "Emphasize preventive care, chronic disease follow-up, and primary-care coordination.",
        "CARDIOLOGY": "Include cardiac risk factors, vitals relevant to CV assessment, and cardiovascular-focused Plan items.",
        "MENTAL_HEALTH": "Use non-stigmatizing language; include safety/risk only when clinically justified by the transcript.",
        "AGED_CARE": "Highlight functional status, falls risk, medications, and caregiver context when mentioned.",
    }
    return addons.get(key, addons["GENERAL"])
