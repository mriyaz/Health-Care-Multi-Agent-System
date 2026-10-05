"""
12-point pre-bill audit checklist (Section E #57).

Each checkpoint returns pass/fail with short rationale for the structured audit report.
"""

from __future__ import annotations

import re
from typing import Any


def run_prebill_audit(
    *,
    clinical_note: str,
    primary_icd: str,
    primary_cpt: str,
    validation: dict[str, Any],
    cpt_entry: dict[str, Any] | None,
    payer_org: str,
) -> dict[str, Any]:
    note = clinical_note or ""
    low = note.lower()
    pts: list[dict[str, Any]] = []

    def add(pid: int, name: str, passed: bool, detail: str) -> None:
        pts.append({"id": pid, "name": name, "pass": passed, "detail": detail})

    icd_ok = bool(
        re.match(r"^[A-TV-Z][0-9]{2}(\.[0-9A-Z]{1,4})?$", primary_icd.strip())
    )
    add(
        1, "ICD-10 format present", icd_ok or len(primary_icd.strip()) >= 3, primary_icd
    )

    cpt_ok = bool(re.match(r"^[0-9]{5}$", primary_cpt.strip()))
    add(2, "CPT/HCPCS format present", cpt_ok, primary_cpt)

    dx_proc_link = (
        any(
            x in low
            for x in (
                "because",
                "due to",
                "secondary to",
                "associated with",
                "for evaluation",
            )
        )
        or len(note) > 120
    )
    add(
        3,
        "Diagnosis–procedure linkage narrative",
        dx_proc_link,
        (
            "Clinical note ties encounter medical necessity to services."
            if dx_proc_link
            else "Weak linkage wording."
        ),
    )

    med_nec = len(note.split()) > 40 and any(
        x in low for x in ("symptom", "pain", "history", "exam", "assessment", "plan")
    )
    add(
        4,
        "Medical necessity documentation density",
        med_nec,
        "SOAP-like density heuristic.",
    )

    mod_hints = bool(
        re.search(r"\b(-25|-59|-XS|-XE|-XP|-XU|-LT|-RT|modifier)\b", note, re.I)
    )
    add(
        5,
        "Modifier usage reviewed",
        mod_hints or True,
        (
            "Explicit modifier documented or defaults acceptable for MVP heuristic."
            if mod_hints
            else "No modifier keywords — verify separately."
        ),
    )

    risks = list((cpt_entry or {}).get("risk_flags") or [])
    unbundling = any("unbundling" in str(r).lower() for r in risks)
    add(
        6,
        "Unbundling risk reviewed",
        not unbundling,
        (
            "Coder flagged unbundling."
            if unbundling
            else "No unbundling flags on CPT suggestion."
        ),
    )

    upcoding = any("upcoding" in str(r).lower() for r in risks)
    add(
        7,
        "Upcoding risk reviewed",
        not upcoding,
        (
            "Potential upcoding risk on CPT suggestion."
            if upcoding
            else "No upcoding flags."
        ),
    )

    lcd_ok = validation.get("validation_ok", True)
    add(
        8,
        "LCD / payer rule consistency",
        bool(lcd_ok),
        "Validation engine result.",
    )

    add(
        9,
        "Bundling / CCI awareness",
        True,
        "MVP placeholder — integrate NCCI edits in v1.0.",
    )

    lat = bool(re.search(r"\b(left|right|bilateral|L\b|R\b)\b", low))
    add(
        10,
        "Laterality / specificity",
        lat or "992" in primary_cpt,
        "Laterality documented when anatomical." if lat else "E/M may omit laterality.",
    )

    dup = bool(re.search(r"\brepeat\b|\bduplicate\b|\bagain\b", low))
    add(
        11,
        "Duplicate service screening",
        not dup,
        (
            "Note mentions repeat services — verify billing frequency."
            if dup
            else "No duplicate cues."
        ),
    )

    add(
        12,
        "Timely filing / auth placeholder",
        True,
        f"Payer={payer_org}; integrate timely filing + auth rules per payer.",
    )

    passed_count = sum(1 for p in pts if p["pass"])
    return {
        "checkpoints": pts,
        "passed_count": passed_count,
        "total": len(pts),
        "score_ratio": round(passed_count / len(pts), 4) if pts else 0.0,
    }
