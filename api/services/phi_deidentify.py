"""
PHI de-identification for transcript/note text before external LLM calls (Section D #40, Section K #111).

Uses deterministic placeholder tokens so outputs can be re-linked without storing PHI in prompts sent upstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeidentifyResult:
    """Sanitized text plus reversible token map for post-processing."""

    text: str
    token_map: dict[str, str]


_PHI_TOKEN_FMT = "[[PHI_{idx}]]"


def _next_placeholder(counter: list[int]) -> str:
    counter[0] += 1
    return _PHI_TOKEN_FMT.format(idx=counter[0])


_PATTERNS: list[tuple[str, str]] = [
    (r"\b\d{3}-\d{2}-\d{4}\b", "SSN-like"),
    (r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b", "phone-us"),
    (
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "email",
    ),
    (
        r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b",
        "date-mdY",
    ),
    (
        r"\b(?:19|20)\d{2}[/-](?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])\b",
        "date-Ymd",
    ),
    (r"\bMRN[:\s#-]*[A-Za-z0-9]{4,}\b", "mrn"),
    (r"\bAccount[:\s#-]*[0-9]{4,}\b", "account"),
]


def deidentify_clinical_text(raw: str) -> DeidentifyResult:
    """
    Replace common US-PHI patterns with ``[[PHI_n]]`` placeholders.

    This is a best-effort regex pipeline — production should add NER (e.g. spaCy
    + scispaCy) and tenant policy; the contract (strip before cloud LLM) is what
    the checklist requires.
    """
    if not raw:
        return DeidentifyResult(text="", token_map={})

    token_map: dict[str, str] = {}
    counter = [0]
    out = raw

    for pattern, _label in _PATTERNS:

        def repl(m: re.Match[str]) -> str:
            ph = _next_placeholder(counter)
            token_map[ph] = m.group(0)
            return ph

        out = re.sub(pattern, repl, out, flags=re.IGNORECASE)

    return DeidentifyResult(text=out, token_map=token_map)


def relink_placeholders(text: str, token_map: dict[str, str]) -> str:
    """Restore original substrings from ``deidentify_clinical_text`` output."""
    if not text or not token_map:
        return text
    out = text
    for ph, orig in sorted(token_map.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(ph, orig)
    return out


def relink_json_values(obj: Any, token_map: dict[str, str]) -> Any:
    """Re-link all string values in a nested JSON-like structure."""
    if isinstance(obj, str):
        return relink_placeholders(obj, token_map)
    if isinstance(obj, list):
        return [relink_json_values(x, token_map) for x in obj]
    if isinstance(obj, dict):
        return {k: relink_json_values(v, token_map) for k, v in obj.items()}
    return obj
