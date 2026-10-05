"""SOAP completeness and confidence scoring (Section D #42, #43)."""

from __future__ import annotations

from typing import Any


def _words(s: str) -> int:
    return len((s or "").split())


def validate_soap_structure(
    soap: dict[str, Any],
    *,
    min_words_per_section: int = 8,
) -> tuple[float, list[str]]:
    """
    Return (structural_confidence 0..1, sections_flagged).

    Each of S/O/A/P must exist and meet minimum word count.
    """
    required = ("subjective", "objective", "assessment", "plan")
    flagged: list[str] = []
    scores: list[float] = []

    for key in required:
        val = soap.get(key)
        text = val if isinstance(val, str) else ""
        wc = _words(text)
        if wc < min_words_per_section:
            flagged.append(key)
            scores.append(0.0)
        else:
            scores.append(1.0)

    if not scores:
        return 0.0, flagged
    structural = sum(scores) / len(scores)
    return structural, flagged


def combined_documentation_confidence(
    llm_confidence: float,
    structural_confidence: float,
) -> float:
    """Blend model-reported confidence with structural SOAP completeness."""
    return max(0.0, min(1.0, min(float(llm_confidence), float(structural_confidence))))
