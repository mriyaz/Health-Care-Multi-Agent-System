"""
Code validation engine (Section E #56): ICD-10 + CPT vs retrieved payer / LCD rules.

Returns machine-readable reason codes suitable for clearinghouse edits and appeals prep.
"""

from __future__ import annotations

from typing import Any


def _norm_codes(raw: list[str] | None) -> set[str]:
    if not raw:
        return set()
    out: set[str] = set()
    for c in raw:
        s = str(c).strip().upper().replace(".", "")
        if s:
            out.add(s)
    return out


def validate_codes_against_rules(
    *,
    primary_icd: str,
    primary_cpt: str,
    all_icd: list[str],
    all_cpt: list[str],
    retrieved_rules: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Compare suggested primary codes against LCD-like rule rows (from Weaviate or seed).

    ``retrieved_rules`` entries may include ``icd10_codes``, ``cpt_codes``, ``rule_kind``,
    ``policy_identifier``, ``title``, ``rule_narrative``.
    """
    picd = primary_icd.strip().upper().replace(".", "")
    pcpt = primary_cpt.strip().upper()
    flags: list[str] = []
    reasons: list[dict[str, Any]] = []

    icd_set = _norm_codes(all_icd)
    cpt_set = _norm_codes(all_cpt)

    if not picd or len(picd) < 3:
        flags.append("ICD_FORMAT_WEAK")
        reasons.append(
            {
                "reason_code": "ICD_FORMAT_WEAK",
                "severity": "medium",
                "detail": "Primary ICD-10 appears incomplete or malformed.",
            }
        )

    if not pcpt or not pcpt.isdigit():
        flags.append("CPT_FORMAT_WEAK")
        reasons.append(
            {
                "reason_code": "CPT_FORMAT_WEAK",
                "severity": "medium",
                "detail": "Primary CPT/HCPCS appears incomplete or malformed.",
            }
        )

    matched_support = False
    matched_conflict = False

    for rule in retrieved_rules:
        if not isinstance(rule, dict):
            continue
        ricd = _norm_codes([str(x) for x in (rule.get("icd10_codes") or [])])
        rcpt = _norm_codes([str(x) for x in (rule.get("cpt_codes") or [])])
        narrative = str(rule.get("rule_narrative") or "").lower()

        if ricd and picd not in ricd and icd_set and icd_set.isdisjoint(ricd):
            continue
        if rcpt and pcpt not in rcpt and cpt_set and cpt_set.isdisjoint(rcpt):
            continue

        matched_support = True

        if "non-covered" in narrative or "not medically necessary" in narrative:
            matched_conflict = True
            reasons.append(
                {
                    "reason_code": "LCD_NON_COVERAGE_LANGUAGE",
                    "severity": "high",
                    "policy_identifier": rule.get("policy_identifier"),
                    "detail": "Rule narrative suggests non-coverage or limited indication.",
                }
            )

        if ricd and picd not in ricd:
            reasons.append(
                {
                    "reason_code": "ICD_OUTSIDE_LCD_INDICATION",
                    "severity": "medium",
                    "policy_identifier": rule.get("policy_identifier"),
                    "detail": f"Primary ICD {picd} not listed in rule ICD set.",
                }
            )
            flags.append("ICD_LCD_MISMATCH")

        if rcpt and pcpt not in rcpt:
            reasons.append(
                {
                    "reason_code": "CPT_OUTSIDE_LCD_SCOPE",
                    "severity": "medium",
                    "policy_identifier": rule.get("policy_identifier"),
                    "detail": f"Primary CPT {pcpt} not listed in rule CPT set.",
                }
            )
            flags.append("CPT_LCD_MISMATCH")

    if retrieved_rules and not matched_support:
        flags.append("NO_RULE_MATCH_REVIEW_NEEDED")
        reasons.append(
            {
                "reason_code": "NO_RULE_MATCH_REVIEW_NEEDED",
                "severity": "low",
                "detail": "No payer rule chunk strongly matched this ICD+CPT pair — manual LCD lookup advised.",
            }
        )

    ok = (
        not matched_conflict
        and "ICD_LCD_MISMATCH" not in flags
        and "CPT_LCD_MISMATCH" not in flags
    )

    return {
        "validation_ok": ok,
        "flags": sorted(set(flags)),
        "reasons": reasons,
        "primary_icd": picd,
        "primary_cpt": pcpt,
    }
