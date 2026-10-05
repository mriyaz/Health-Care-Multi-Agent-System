"""
SMART on FHIR OAuth2 helpers (Checklist #24, P1).

These functions do not start a browser flow; they fetch ``.well-known/smart-configuration``
and build URLs / exchange codes so your EHR embed can complete the OAuth dance.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

import httpx


async def fetch_smart_configuration(
    issuer: str,
    http: httpx.AsyncClient,
) -> dict[str, Any]:
    """
    GET ``{issuer}/.well-known/smart-configuration`` (or ``smart-configuration.json`` fallback).
    """
    base = issuer.rstrip("/")
    for suffix in (
        "/.well-known/smart-configuration",
        "/.well-known/smart-configuration.json",
    ):
        url = f"{base}{suffix}"
        r = await http.get(url, timeout=20.0)
        if r.is_success:
            return r.json()
    raise RuntimeError(f"SMART configuration not found for issuer {issuer!r}")


def build_authorize_url(
    *,
    authorize_endpoint: str,
    client_id: str,
    redirect_uri: str,
    scope: str,
    state: str,
    aud: Optional[str] = None,
    pkce_challenge: Optional[str] = None,
    pkce_method: str = "S256",
) -> str:
    params: dict[str, str] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
    }
    if aud:
        params["aud"] = aud
    if pkce_challenge:
        params["code_challenge"] = pkce_challenge
        params["code_challenge_method"] = pkce_method
    return f"{authorize_endpoint}?{urlencode(params)}"


async def exchange_authorization_code(
    *,
    token_endpoint: str,
    client_id: str,
    client_secret: Optional[str],
    redirect_uri: str,
    code: str,
    http: httpx.AsyncClient,
    code_verifier: Optional[str] = None,
) -> dict[str, Any]:
    """POST application/x-www-form-urlencoded token request (authorization_code grant)."""
    data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }
    if client_secret:
        data["client_secret"] = client_secret
    if code_verifier:
        data["code_verifier"] = code_verifier
    r = await http.post(
        token_endpoint,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()
