"""
Phrase-level attribution for ICD/CPT recommendations (Section E #54).

Full clinical pipelines often use SHAP on transformer logits. Here we implement an
**additive leave-one-out (LOO) marginal** explanation: importance of each sentence
is proportional to how much a lexical relevance score drops when that sentence
is removed. Values are normalized to sum to 1 per code — analogous to Shapley-style
marginal contributions for modular text.

When you deploy ClinicalBERT + TreeSHAP / Deep SHAP, swap the ``score()`` function
and keep the same JSON schema for the audit report.
"""

from __future__ import annotations

import math
import re
from typing import Any


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^\w]+", text.lower()) if len(t) > 2}


def _lexical_score(note: str, code: str, description: str) -> float:
    """Deterministic relevance proxy (BM25-style overlap without corpus stats)."""
    bow_code = _tokens(f"{code} {description}")
    if not bow_code:
        return 0.0
    chunks = re.split(r"(?<=[.!?])\s+|\n+", note.strip())
    chunks = [c.strip() for c in chunks if c.strip()]
    if not chunks:
        return 0.0
    total = 0.0
    for ch in chunks:
        inter = len(_tokens(ch) & bow_code)
        total += inter / math.sqrt(len(bow_code) + 1.0)
    return total / max(1, len(chunks))


def phrase_attributions_for_code(
    clinical_note: str,
    *,
    code: str,
    description: str,
    max_phrases: int = 8,
) -> dict[str, Any]:
    """
    Return pseudo-SHAP style phrase weights for one code.

    Output matches downstream audit schema: ``phrases`` list with ``shap_value``.
    """
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+|\n+", clinical_note.strip())
        if s.strip()
    ]
    if not sentences:
        return {
            "code": code,
            "description": description,
            "attribution_method": "loo_marginal_lexical",
            "phrases": [],
        }

    full = _lexical_score(clinical_note, code, description)
    marginals: list[tuple[str, float]] = []
    joined = clinical_note.strip()
    for sent in sentences:
        remainder = joined.replace(sent, " ", 1).strip()
        without = _lexical_score(remainder, code, description)
        marginals.append((sent, max(0.0, full - without)))

    total_m = sum(m for _, m in marginals) or 1.0
    phrases: list[dict[str, Any]] = []
    ranked = sorted(marginals, key=lambda x: x[1], reverse=True)
    for i, (sent, m) in enumerate(ranked[:max_phrases]):
        phrases.append(
            {
                "phrase": sent[:500],
                "shap_value": round(m / total_m, 6),
                "rank": i + 1,
            }
        )

    return {
        "code": code,
        "description": description,
        "attribution_method": "loo_marginal_lexical",
        "note": "Approximates marginal phrase importance; replace with SHAP on ClinicalBERT for production.",
        "phrases": phrases,
    }
