"""
Generic FHIR resource CRUD wrapper (Checklist #15 base class pattern).
"""

from __future__ import annotations

from typing import Any, Optional

from api.fhir.client import FhirRestClient


class FhirResourceRepository:
    """
    Typed-ish CRUD for a single ``resourceType`` string (Patient, Encounter, …).
    """

    resource_type: str

    def __init__(self, client: FhirRestClient, resource_type: str) -> None:
        self._client = client
        self.resource_type = resource_type

    async def read(self, logical_id: str) -> dict[str, Any]:
        return await self._client.read(self.resource_type, logical_id)

    async def create(
        self,
        resource: dict[str, Any],
        *,
        prefer_return: bool = True,
    ) -> dict[str, Any]:
        body = dict(resource)
        body.setdefault("resourceType", self.resource_type)
        return await self._client.create(
            self.resource_type,
            body,
            prefer_return=prefer_return,
        )

    async def update(
        self,
        logical_id: str,
        resource: dict[str, Any],
        *,
        prefer_return: bool = True,
    ) -> dict[str, Any]:
        body = dict(resource)
        body["resourceType"] = self.resource_type
        body["id"] = logical_id
        return await self._client.update(
            self.resource_type,
            logical_id,
            body,
            prefer_return=prefer_return,
        )

    async def delete(self, logical_id: str) -> None:
        await self._client.delete(self.resource_type, logical_id)

    async def search(self, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return await self._client.search(self.resource_type, params=params or {})
