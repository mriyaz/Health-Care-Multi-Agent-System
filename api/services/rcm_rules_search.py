"""
Retrieve payer / LCD rule chunks from Weaviate ``payer_rules`` (Section E #55–56).

Uses BM25 against ``rule_narrative`` and CPT/ICD hints embedded in the query string.
Falls back to in-memory seed rows when the client is unavailable (unit tests).
"""

from __future__ import annotations

import logging
from typing import Any

import weaviate

from api.services.rcm_payer_seed import fetch_rules_fallback_global
from api.vectorstore.collections import PAYER_RULES

logger = logging.getLogger(__name__)


def _rule_from_obj(obj: Any) -> dict[str, Any]:
    props = getattr(obj, "properties", None) or {}
    if not isinstance(props, dict):
        return {}
    return {
        "tenant_id": props.get("tenant_id"),
        "payer_org_identifier": props.get("payer_org_identifier"),
        "rule_kind": props.get("rule_kind"),
        "policy_identifier": props.get("policy_identifier"),
        "title": props.get("title"),
        "rule_narrative": props.get("rule_narrative"),
        "cpt_codes": list(props.get("cpt_codes") or []),
        "icd10_codes": list(props.get("icd10_codes") or []),
        "modifiers": list(props.get("modifiers") or []),
    }


def search_payer_rules(
    client: weaviate.WeaviateClient | None,
    *,
    tenant_id: str,
    payer_org_identifier: str,
    clinical_note_excerpt: str,
    cpt_hint: str,
    icd_hint: str,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """
    Return merged rule dicts for validation + audit narrative citations.
    """
    q = " ".join(
        [
            payer_org_identifier,
            clinical_note_excerpt[:1200],
            f"CPT {cpt_hint}",
            f"ICD {icd_hint}",
        ]
    ).strip()

    if client is None:
        fb = fetch_rules_fallback_global()
        return _rank_fallback(fb, cpt_hint, icd_hint, limit)

    try:
        coll = client.collections.get(PAYER_RULES)
        res = coll.query.bm25(query=q, limit=limit)
        objs = getattr(res, "objects", None) or []
        rules = [_rule_from_obj(o) for o in objs]
        return [r for r in rules if r]
    except Exception:
        logger.exception("weaviate_bm25_failed")
        fb = fetch_rules_fallback_global()
        return _rank_fallback(fb, cpt_hint, icd_hint, limit)


def _rank_fallback(
    rows: list[dict[str, Any]], cpt: str, icd: str, limit: int
) -> list[dict[str, Any]]:
    cpt_u = cpt.upper().strip()
    icd_u = icd.upper().replace(".", "").strip()
    scored: list[tuple[float, dict[str, Any]]] = []
    for r in rows:
        cs = [str(x).upper() for x in (r.get("cpt_codes") or [])]
        ds = [str(x).upper().replace(".", "") for x in (r.get("icd10_codes") or [])]
        score = 0.0
        if cpt_u and cpt_u in cs:
            score += 3.0
        if icd_u and icd_u in ds:
            score += 2.0
        score += min(1.0, len(str(r.get("rule_narrative") or "")) / 5000.0)
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]
