"""MedicationRequest — read active; write only draft/proposal (Checklist #22, P1)."""

from __future__ import annotations

from typing import Any

from api.fhir.crud import FhirResourceRepository
from api.fhir.mappers import enforce_medication_request_draft_safe


class MedicationRequestFhirHandler:
    resource_type = "MedicationRequest"

    def __init__(self, repo: FhirResourceRepository) -> None:
        self._repo = repo

    async def read_fhir(self, logical_id: str) -> dict[str, Any]:
        return await self._repo.read(logical_id)

    async def create_fhir_draft_only(self, resource: dict[str, Any]) -> dict[str, Any]:
        body = enforce_medication_request_draft_safe(resource)
        return await self._repo.create(body)

    async def create_fhir(self, resource: dict[str, Any]) -> dict[str, Any]:
        return await self.create_fhir_draft_only(resource)

    async def update_fhir(
        self, logical_id: str, resource: dict[str, Any]
    ) -> dict[str, Any]:
        body = enforce_medication_request_draft_safe(resource)
        body["id"] = logical_id
        return await self._repo.update(logical_id, body)

    async def delete_fhir(self, logical_id: str) -> None:
        await self._repo.delete(logical_id)

    async def search_fhir(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._repo.search(params)
