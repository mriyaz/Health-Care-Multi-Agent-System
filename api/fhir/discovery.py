"""
Resolve a working FHIR base URL (root vs ``/fhir`` suffix), same idea as ``scripts/seed_hapi_fhir.py``.
"""

from __future__ import annotations

from typing import Iterable

import httpx

from api.fhir.client import FHIR_JSON_HEADERS


async def resolve_fhir_base_url(client: httpx.AsyncClient, raw_base_url: str) -> str:
    """
    Try ``raw_base_url`` and a small set of variants until ``GET {base}/metadata`` succeeds.
    """
    candidates: list[str] = []
    base = raw_base_url.rstrip("/")
    candidates.append(base)
    if not base.endswith("/fhir"):
        candidates.append(f"{base}/fhir")
    else:
        candidates.append(base.removesuffix("/fhir"))

    seen: set[str] = set()
    ordered: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    last_error: str | None = None
    for base_url in ordered:
        try:
            r = await client.get(
                f"{base_url}/metadata",
                headers=dict(FHIR_JSON_HEADERS),
                timeout=15.0,
            )
            if r.is_success:
                return base_url
            last_error = f"{r.status_code} {r.reason_phrase}"
        except httpx.RequestError as exc:
            last_error = str(exc)
            continue

    raise RuntimeError(
        f"Could not resolve FHIR metadata at {raw_base_url!r}. Last error: {last_error}"
    )


def candidate_bases(raw: str) -> Iterable[str]:
    """Synchronous variant for tests / tooling."""
    base = raw.rstrip("/")
    yield base
    if not base.endswith("/fhir"):
        yield f"{base}/fhir"
    else:
        yield base.removesuffix("/fhir")
