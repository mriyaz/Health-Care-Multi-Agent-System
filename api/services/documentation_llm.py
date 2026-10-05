"""
LLM-backed generators for SOAP, discharge summary, and referral letter (Section D #41, #46, #47).

Uses OpenRouter (OpenAI-compatible) as the project's configured remote model for generation tasks.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from api.llm.openrouter_client import OpenRouterClient
from api.services.note_templates import specialty_system_addon
from api.settings import Settings

logger = logging.getLogger(__name__)


def _parse_json_object(raw: str) -> dict[str, Any]:
    """
    Parse a JSON object from LLM output.

    Models often wrap JSON in prose and/or markdown fences despite instructions.
    """
    text = raw.strip()
    if not text:
        raise json.JSONDecodeError("empty response", text, 0)

    candidates: list[str] = []

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE):
        block = match.group(1).strip()
        if block:
            candidates.append(block)

    if text.startswith("```"):
        block = text.split("```", 2)[1]
        if block.lower().startswith("json"):
            block = block[4:].lstrip()
        block = block.strip()
        if block:
            candidates.append(block)

    candidates.append(text)

    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break

    seen: set[str] = set()
    last_exc: json.JSONDecodeError | None = None
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_exc = exc
            continue
        if isinstance(parsed, dict):
            return parsed

    if last_exc is not None:
        raise last_exc
    raise json.JSONDecodeError("no json object found", text, 0)


async def generate_soap_note(
    *,
    settings: Settings,
    openrouter: OpenRouterClient,
    deidentified_transcript: str,
    specialty: str = "GENERAL",
) -> tuple[dict[str, Any], str, int, float, dict[str, Any]]:
    """
    Returns soap_dict, model_used, latency_ms, token_estimate, usage_raw.
    """
    model = settings.documentation_soap_model
    addon = specialty_system_addon(specialty)
    system = (
        "You are a clinical documentation assistant for US outpatient encounters. "
        f"{addon}\n"
        "Return ONLY a single raw JSON object (no markdown fences, no prose before or after) with keys: "
        "subjective, objective, assessment, plan (each string in SOAP style), "
        "icd10_suggestions (array of up to 5 objects with code and rationale), "
        "confidence (float 0-1 for overall charting quality).\n"
        "Use only information inferable from the transcript; do not invent severe diagnoses."
    )
    user = f"Transcript (de-identified placeholders may appear):\n{deidentified_transcript}"
    t0 = time.perf_counter()
    result = await openrouter.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_completion_tokens=settings.documentation_max_completion_tokens,
        langfuse_task_type="documentation_soap",
        langfuse_metadata={"model": model, "specialty": specialty},
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    try:
        payload = _parse_json_object(result.content)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("soap_json_parse_failed", extra={"error": str(exc)})
        payload = {
            "subjective": result.content[:2000],
            "objective": "",
            "assessment": "",
            "plan": "",
            "icd10_suggestions": [],
            "confidence": 0.55,
        }
    usage = dict(result.usage) if isinstance(result.usage, dict) else {}
    tokens = int(
        usage.get("total_tokens")
        or ((usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))
        or 0
    )
    return payload, result.model, latency_ms, float(tokens), usage


async def generate_discharge_summary(
    *,
    settings: Settings,
    openrouter: OpenRouterClient,
    deidentified_bundle: str,
    specialty: str = "GENERAL",
) -> tuple[dict[str, Any], str, int, float, dict[str, Any]]:
    """Structured discharge summary — HITL is enforced downstream via confidence gate."""
    model = settings.documentation_discharge_model
    addon = specialty_system_addon(specialty)
    system = (
        "You produce concise hospital-style discharge summaries for the US. "
        f"{addon}\n"
        "Return ONE JSON object with keys: "
        "summary (string), "
        "diagnosis_list (array of strings), "
        "medications (array of strings), "
        "follow_up (string), "
        "patient_instructions (string), "
        "confidence (float 0-1)."
    )
    t0 = time.perf_counter()
    result = await openrouter.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": deidentified_bundle},
        ],
        temperature=0.2,
        max_completion_tokens=min(
            4096, settings.documentation_max_completion_tokens * 2
        ),
        langfuse_task_type="documentation_discharge",
        langfuse_metadata={"model": model},
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    try:
        payload = _parse_json_object(result.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        payload = {
            "summary": result.content[:4000],
            "diagnosis_list": [],
            "medications": [],
            "follow_up": "",
            "patient_instructions": "",
            "confidence": 0.55,
        }
    usage = dict(result.usage) if isinstance(result.usage, dict) else {}
    tokens = int(usage.get("total_tokens") or 0)
    return payload, result.model, latency_ms, float(tokens), usage


async def generate_referral_letter(
    *,
    settings: Settings,
    openrouter: OpenRouterClient,
    deidentified_bundle: str,
    specialty: str = "GENERAL",
) -> tuple[dict[str, Any], str, int, float, dict[str, Any]]:
    """Referral letter draft for clinician edit/approval."""
    model = settings.documentation_referral_model
    addon = specialty_system_addon(specialty)
    system = (
        "You draft specialty referral letters for US clinicians. "
        f"{addon}\n"
        "Return ONE JSON object with keys: "
        "letter_body (string, formal letter), "
        "reason_for_referral (string), "
        "relevant_history (string), "
        "confidence (float 0-1)."
    )
    t0 = time.perf_counter()
    result = await openrouter.chat_completion(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": deidentified_bundle},
        ],
        temperature=0.25,
        max_completion_tokens=settings.documentation_max_completion_tokens,
        langfuse_task_type="documentation_referral",
        langfuse_metadata={"model": model},
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    try:
        payload = _parse_json_object(result.content)
    except (json.JSONDecodeError, TypeError, ValueError):
        payload = {
            "letter_body": result.content[:4000],
            "reason_for_referral": "",
            "relevant_history": "",
            "confidence": 0.55,
        }
    usage = dict(result.usage) if isinstance(result.usage, dict) else {}
    tokens = int(usage.get("total_tokens") or 0)
    return payload, result.model, latency_ms, float(tokens), usage


def soap_payload_to_note_soap(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize generator output to Note.soap JSON."""
    plan = str(payload.get("plan") or "")
    icd10 = payload.get("icd10_suggestions") or []
    if icd10 and isinstance(icd10, list):
        lines = []
        for item in icd10:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            rationale = str(item.get("rationale") or "").strip()
            if code and rationale:
                lines.append(f"{code}: {rationale}")
            elif code:
                lines.append(code)
        if lines:
            icd_block = "ICD-10 suggestions:\n" + "\n".join(
                f"- {line}" for line in lines
            )
            plan = f"{plan}\n\n{icd_block}".strip() if plan else icd_block
    return {
        "subjective": str(payload.get("subjective") or ""),
        "objective": str(payload.get("objective") or ""),
        "assessment": str(payload.get("assessment") or ""),
        "plan": plan,
        "icd10_suggestions": icd10,
    }


def discharge_payload_to_soap_shape(payload: dict[str, Any]) -> dict[str, Any]:
    """Store discharge summary in SOAP-shaped JSON for unified Note rendering."""
    summary = str(payload.get("summary") or "")
    dx = payload.get("diagnosis_list") or []
    meds = payload.get("medications") or []
    return {
        "subjective": summary[:8000],
        "objective": "Medications: " + "; ".join(str(x) for x in meds)[:8000],
        "assessment": "Diagnoses: " + "; ".join(str(x) for x in dx)[:8000],
        "plan": (
            "Follow-up: "
            + str(payload.get("follow_up") or "")
            + "\nPatient instructions: "
            + str(payload.get("patient_instructions") or "")
        )[:8000],
        "kind": "discharge_summary",
        "structured": payload,
    }


def referral_payload_to_soap_shape(payload: dict[str, Any]) -> dict[str, Any]:
    body = str(payload.get("letter_body") or "")
    return {
        "subjective": body[:8000],
        "objective": str(payload.get("relevant_history") or "")[:8000],
        "assessment": str(payload.get("reason_for_referral") or "")[:8000],
        "plan": "See referral letter body for coordination items.",
        "kind": "referral_letter",
        "structured": payload,
    }
