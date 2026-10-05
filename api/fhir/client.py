"""
Async FHIR REST client (R4 JSON).

All network I/O goes through ``httpx``; callers map responses to ``fhir.resources`` models.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx


FHIR_JSON_HEADERS = {
    "Accept": "application/fhir+json",
    "Content-Type": "application/fhir+json",
}


class FhirRestError(Exception):
    """FHIR server returned a non-success HTTP status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class FhirRestClient:
    """
    Minimal CRUD + search against a FHIR base URL (e.g. ``http://localhost:8082/fhir``).
    """

    def __init__(
        self,
        *,
        base_url: str,
        http: httpx.AsyncClient,
        default_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._http = http
        self._headers = dict(default_headers or FHIR_JSON_HEADERS)

    @property
    def base_url(self) -> str:
        return self._base

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self._base}/{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> httpx.Response:
        merged = {**self._headers, **(headers or {})}
        return await self._http.request(
            method,
            self._url(path),
            json=json,
            params=params,
            headers=merged,
        )

    def _raise_for_fhir(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        body = response.text
        raise FhirRestError(
            f"FHIR request failed: {response.status_code} {response.reason_phrase}",
            status_code=response.status_code,
            body=body[:8000] if body else None,
        )

    async def read(self, resource_type: str, logical_id: str) -> dict[str, Any]:
        r = await self._request("GET", f"{resource_type}/{logical_id}")
        self._raise_for_fhir(r)
        return r.json()

    async def create(
        self,
        resource_type: str,
        resource: dict[str, Any],
        *,
        prefer_return: bool = True,
    ) -> dict[str, Any]:
        headers = {}
        if prefer_return:
            headers["Prefer"] = "return=representation"
        r = await self._request(
            "POST",
            resource_type,
            json=resource,
            headers=headers,
        )
        self._raise_for_fhir(r)
        if r.content:
            return r.json()
        # Some servers honor return=minimal — caller may need Location header
        return {"resourceType": resource_type, "id": "", "meta": {}}

    async def update(
        self,
        resource_type: str,
        logical_id: str,
        resource: dict[str, Any],
        *,
        prefer_return: bool = True,
    ) -> dict[str, Any]:
        headers = {}
        if prefer_return:
            headers["Prefer"] = "return=representation"
        r = await self._request(
            "PUT",
            f"{resource_type}/{logical_id}",
            json=resource,
            headers=headers,
        )
        self._raise_for_fhir(r)
        if r.content:
            return r.json()
        return await self.read(resource_type, logical_id)

    async def delete(self, resource_type: str, logical_id: str) -> None:
        r = await self._request("DELETE", f"{resource_type}/{logical_id}")
        if r.status_code not in (200, 204):
            self._raise_for_fhir(r)

    async def search(
        self,
        resource_type: str,
        params: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        r = await self._request("GET", resource_type, params=params)
        self._raise_for_fhir(r)
        return r.json()

    async def transaction(self, bundle: dict[str, Any]) -> dict[str, Any]:
        r = await self._request("POST", "", json=bundle)
        self._raise_for_fhir(r)
        return r.json()

    async def metadata(self) -> dict[str, Any]:
        r = await self._request("GET", "metadata")
        self._raise_for_fhir(r)
        return r.json()
