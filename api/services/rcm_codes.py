"""
ICD-10 / CPT suggestion helpers for the RCM agent (Section E #52–53).

Production intent: swap the LLM JSON path for a ClinicalBERT + beam search ranker.
MVP: structured OpenRouter output with calibrated confidences; deterministic heuristic stub
when no API key (tests / offline dev).
"""

from __future__ import annotations

import json
import re
from typing import Any

from api.llm.openrouter_client import OpenRouterClient
from api.settings import Settings

# Minimal keyword → code hints for offline stub (not exhaustive — demo-safe).
_STUB_ICD_RULES: list[tuple[str, str, str]] = [
    (
        r"\bdiabetes\b|\bdm\b|\bT2DM\b|\btype\s*2\s*diabetes",
        "E11.9",
        "Type 2 diabetes mellitus without complications",
    ),
    (
        r"\bhypertension\b|\bHTN\b|\bhigh blood pressure",
        "I10",
        "Essential (primary) hypertension",
    ),
    (r"\basthma\b", "J45.909", "Unspecified asthma, uncomplicated"),
    (r"\bCHF\b|\bheart failure\b", "I50.9", "Heart failure, unspecified"),
    (r"\bCOPD\b", "J44.9", "Chronic obstructive pulmonary disease, unspecified"),
    (r"\bpneumonia\b", "J18.9", "Pneumonia, unspecified organism"),
    (
        r"\boutpatient\b|\bfollow[- ]?up\b|\bestablished patient\b",
        "Z09",
        "Encounter for follow-up examination after completed treatment",
    ),
]

_STUB_CPT_RULES: list[tuple[str, str, str, list[str]]] = [
    (
        r"\bestablished patient\b|\boffice visit\b|\bfollow[- ]?up visit\b",
        "99213",
        "Office or other outpatient visit, established patient, level 3",
        [],
    ),
    (
        r"\bmoderate complexity\b|\bmultiple problems\b|\blonger visit\b",
        "99214",
        "Office or other outpatient visit, established patient, level 4",
        ["upcoding_risk_if_documentation_insufficient"],
    ),
    (
        r"\bMRI\b|\bmagnetic resonance\b",
        "73721",
        "MRI joint upper extremity without contrast",
        ["unbundling_if_contrast_separately_reported"],
    ),
    (
        r"\barthroscopy\b|\bknee scope\b",
        "29881",
        "Knee arthroscopy/surgery",
        ["global_period_review"],
    ),
    (
        r"\bprocedure\b|\bsurgery\b|\binjection\b",
        "99214",
        "Consider E/M level with procedure — verify modifier usage",
        ["modifier_51_review"],
    ),
]


def _stub_icd(note: str) -> list[dict[str, Any]]:
    low = note.lower()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pat, code, desc in _STUB_ICD_RULES:
        if re.search(pat, low, re.I) and code not in seen:
            seen.add(code)
            conf = min(0.92, 0.65 + 0.05 * len(out))
            out.append(
                {
                    "code": code,
                    "description": desc,
                    "confidence": round(conf, 3),
                    "source": "heuristic_stub",
                }
            )
        if len(out) >= 3:
            break
    if not out:
        out.append(
            {
                "code": "R69",
                "description": "Illness, unspecified",
                "confidence": 0.55,
                "source": "heuristic_stub_fallback",
            }
        )
    return out[:3]


def _stub_cpt(note: str, specialty: str) -> list[dict[str, Any]]:
    low = note.lower()
    sp = (specialty or "GENERAL").upper()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pat, code, desc, risks in _STUB_CPT_RULES:
        if re.search(pat, low, re.I) and code not in seen:
            seen.add(code)
            conf = min(0.9, 0.62 + 0.06 * len(out))
            rf = list(risks)
            if sp == "ORTHOPEDICS" and "29881" in code:
                rf.append("specialty_orthopedic_review")
            out.append(
                {
                    "code": code,
                    "description": desc,
                    "confidence": round(conf, 3),
                    "risk_flags": rf,
                    "source": "heuristic_stub",
                }
            )
        if len(out) >= 3:
            break
    if not out:
        out.append(
            {
                "code": "99213",
                "description": "Office visit established level 3 (default stub)",
                "confidence": 0.58,
                "risk_flags": ["default_stub_selection"],
                "source": "heuristic_stub_fallback",
            }
        )
    return out[:3]


async def suggest_icd10_cpt(
    *,
    clinical_note: str,
    specialty: str,
    procedure_description: str | None,
    openrouter: OpenRouterClient | None,
    settings: Settings,
    state: dict[str, Any],
) -> dict[str, Any]:
    """
    Return top-3 ICD-10 and CPT suggestions with confidences and CPT risk flags.

    ``model_versions.rcm_coding_model`` records which path ran.
    """
    proc = (procedure_description or "").strip()
    note_ctx = clinical_note.strip()
    if not settings.resolved_openrouter_api_key or openrouter is None:
        icd = _stub_icd(note_ctx)
        cpt = _stub_cpt(note_ctx + " " + proc, specialty)
        return {
            "icd10": icd,
            "cpt": cpt,
            "model_used": "heuristic_stub",
            "source": "stub",
            "clinicalbert_equivalent": False,
        }

    user_parts = [
        "You are a certified medical coding assistant (ClinicalBERT-equivalent ranking).",
        "Given the clinical note (and optional procedure line), propose exactly the top 3 ICD-10-CM diagnosis codes",
        "and top 3 CPT/HCPCS procedure codes for physician/outpatient billing.",
        "Respond with JSON ONLY:",
        '{"icd10":[{"code":"string","description":"string","confidence":0.0-1.0}],"cpt":[{"code":"string","description":"string","confidence":0.0-1.0,"risk_flags":["string"]}]}',
        "risk_flags may include unbundling_risk, upcoding_risk, modifier_review, medical_necessity_concern.",
        f"SPECIALTY={specialty}.",
    ]
    if proc:
        user_parts.append(f"PROCEDURE_LINE={proc}")
    user_parts.append(f"CLINICAL_NOTE:\n{note_ctx}")

    messages = [
        {"role": "system", "content": "Return compact JSON only. No markdown."},
        {"role": "user", "content": "\n".join(user_parts)},
    ]

    result = await openrouter.chat_completion(
        model=settings.orchestrator_llm_primary_model,
        messages=messages,
        temperature=0.1,
        max_completion_tokens=900,
        langfuse_task_type="rcm_icd_cpt",
        langfuse_metadata={
            "tenant_id": state.get("tenant_id"),
            "task_id": state.get("task_id"),
        },
    )

    raw = result.content.strip()
    # tolerate markdown fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        icd = _stub_icd(note_ctx)
        cpt = _stub_cpt(note_ctx + " " + proc, specialty)
        return {
            "icd10": icd,
            "cpt": cpt,
            "model_used": result.model,
            "source": "llm_json_recover_stub",
            "parse_error": True,
            "clinicalbert_equivalent": False,
        }

    icd_raw = parsed.get("icd10") if isinstance(parsed, dict) else None
    cpt_raw = parsed.get("cpt") if isinstance(parsed, dict) else None
    icd_out: list[dict[str, Any]] = []
    cpt_out: list[dict[str, Any]] = []

    if isinstance(icd_raw, list):
        for item in icd_raw[:3]:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            try:
                conf = float(item.get("confidence", 0.75))
            except (TypeError, ValueError):
                conf = 0.75
            icd_out.append(
                {
                    "code": code,
                    "description": str(item.get("description") or "")[:500],
                    "confidence": max(0.0, min(1.0, conf)),
                    "source": "llm_structured",
                }
            )

    if isinstance(cpt_raw, list):
        for item in cpt_raw[:3]:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            try:
                conf = float(item.get("confidence", 0.75))
            except (TypeError, ValueError):
                conf = 0.75
            risks = item.get("risk_flags")
            if isinstance(risks, list):
                rf = [str(x) for x in risks[:12]]
            elif risks is None:
                rf = []
            else:
                rf = [str(risks)]
            cpt_out.append(
                {
                    "code": code,
                    "description": str(item.get("description") or "")[:500],
                    "confidence": max(0.0, min(1.0, conf)),
                    "risk_flags": rf,
                    "source": "llm_structured",
                }
            )

    if not icd_out:
        icd_out = _stub_icd(note_ctx)
    if not cpt_out:
        cpt_out = _stub_cpt(note_ctx + " " + proc, specialty)

    return {
        "icd10": icd_out[:3],
        "cpt": cpt_out[:3],
        "model_used": result.model,
        "source": "llm",
        "clinicalbert_equivalent": True,
    }
