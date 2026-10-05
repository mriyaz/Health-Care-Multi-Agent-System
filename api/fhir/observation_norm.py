"""
Normalize Observation quantities to UCUM SI where practical (Checklist #20).
"""

from __future__ import annotations

import copy
from typing import Any, Optional


def _as_float(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def normalize_observation(obs: dict[str, Any]) -> dict[str, Any]:
    """
    Return a shallow-deep copy of ``obs`` with ``valueQuantity`` converted when UCUM is known.

    Examples:
    - ``[lb_av]`` body weight → ``kg``
    - ``[in_i]`` height → ``cm``
    - ``Cel`` / ``[degF]`` → ``Cel`` (SI)
    """
    out = copy.deepcopy(obs)
    vq = out.get("valueQuantity")
    if not isinstance(vq, dict):
        return out
    code = (vq.get("code") or "").strip()
    val = _as_float(vq.get("value"))
    if val is None:
        return out

    system = (vq.get("system") or "").lower()
    if system and "unitsofmeasure" not in system and "ucum" not in system:
        return out

    # UCUM mass pound → kg
    if code in ("[lb_av]", "[lb]", "lb_av"):
        vq["value"] = round(val * 0.45359237, 4)
        vq["code"] = "kg"
        vq["unit"] = "kg"
        vq["system"] = "http://unitsofmeasure.org"
        return out

    # inch → cm
    if code in ("[in_i]", "[in]", "in_i"):
        vq["value"] = round(val * 2.54, 4)
        vq["code"] = "cm"
        vq["unit"] = "cm"
        vq["system"] = "http://unitsofmeasure.org"
        return out

    # Fahrenheit → Celsius
    if code in ("[degF]", "[degf]"):
        vq["value"] = round((val - 32.0) * 5.0 / 9.0, 4)
        vq["code"] = "Cel"
        vq["unit"] = "Cel"
        vq["system"] = "http://unitsofmeasure.org"
        return out

    return out
