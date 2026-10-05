"""
Charge capture completeness hints (Section E #64 — P2).

Lightweight lexical checks between narrative and proposed CPT set; integrate fee schedule
and charge master feeds in a future iteration.
"""

from __future__ import annotations

import re
from typing import Any


_HINTS: list[tuple[str, str, str]] = [
    (r"\binjection\b|\bsteroid injection\b", "96372", "Therapeutic injection admin"),
    (r"\bEKG\b|\bECG\b|\belectrocardiogram\b", "93000", "Electrocardiogram"),
    (r"\bwound care\b|\bdebridement\b", "97597", "Selective wound care"),
    (r"\bspirometry\b", "94010", "Spirometry"),
]


def charge_capture_hints(
    clinical_note: str, suggested_cpt_codes: list[str]
) -> dict[str, Any]:
    low = clinical_note.lower()
    codes_upper = {str(c).strip().upper() for c in suggested_cpt_codes}
    gaps: list[dict[str, str]] = []
    for pat, cpt, label in _HINTS:
        if re.search(pat, low, re.I) and cpt not in codes_upper:
            gaps.append(
                {
                    "likely_cpt": cpt,
                    "label": label,
                    "reason": "Narrative mentions service not reflected in top CPT suggestions.",
                }
            )
    return {
        "possible_missed_services": gaps[:10],
        "review_recommended": bool(gaps),
        "detail": "Heuristic only — reconcile against charge ticket and superbill.",
    }
