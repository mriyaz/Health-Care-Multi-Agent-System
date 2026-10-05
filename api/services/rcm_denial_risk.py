"""
Denial risk scoring (Section E #58) + lightweight prediction hook (Section E #62 P1).

Combines coding confidence, payer-rule validation, CPT risk flags, and pre-bill score.
This is a calibrated heuristic suitable for demos; train a classifier on historical
835/277 responses when you have labeled outcomes.
"""

from __future__ import annotations

from typing import Any


def compute_denial_risk_score(
    *,
    icd_confidence: float,
    cpt_confidence: float,
    validation: dict[str, Any],
    prebill_score_ratio: float,
    cpt_risk_flags: list[str],
) -> dict[str, Any]:
    """Return ``risk_score`` in [0, 1] plus contributing factors."""

    v_ok = 1.0 if validation.get("validation_ok") else 0.0
    crit = sum(
        1
        for r in validation.get("reasons") or []
        if isinstance(r, dict) and str(r.get("severity")).lower() == "high"
    )
    flag_penalty = min(0.35, 0.12 * len(validation.get("flags") or []))
    risk_word = min(0.25, 0.05 * len(cpt_risk_flags))

    raw = (
        0.22 * (1.0 - icd_confidence)
        + 0.22 * (1.0 - cpt_confidence)
        + 0.18 * (1.0 - v_ok)
        + 0.15 * (1.0 - prebill_score_ratio)
        + 0.13 * min(1.0, crit * 0.25)
        + flag_penalty
        + risk_word
    )
    risk = max(0.0, min(1.0, raw))

    return {
        "risk_score": round(risk, 4),
        "components": {
            "icd_confidence_penalty": round(0.22 * (1.0 - icd_confidence), 4),
            "cpt_confidence_penalty": round(0.22 * (1.0 - cpt_confidence), 4),
            "validation_penalty": round(0.18 * (1.0 - v_ok), 4),
            "prebill_penalty": round(0.15 * (1.0 - prebill_score_ratio), 4),
            "lcd_conflict_penalty": round(0.13 * min(1.0, crit * 0.25), 4),
            "extra_flags": round(flag_penalty + risk_word, 4),
        },
        "model_kind": "heuristic_v1",
        "prediction_ml_ready": False,
    }
