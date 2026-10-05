"""DocumentReference — clinical notes as FHIR, append-only versioning (Checklist #19)."""

from __future__ import annotations

from typing import Any

from api.fhir.crud import FhirResourceRepository
from api.fhir.mappers import (
    document_reference_with_replaces,
    validate_document_reference,
)


class DocumentReferenceFhirHandler:
    resource_type = "DocumentReference"

    def __init__(self, repo: FhirResourceRepository) -> None:
        self._repo = repo

    async def read_fhir(self, logical_id: str) -> dict[str, Any]:
        return await self._repo.read(logical_id)

    async def create_fhir(self, resource: dict[str, Any]) -> dict[str, Any]:
        body = validate_document_reference(resource)
        return await self._repo.create(body)

    async def create_superseding_version(
        self,
        *,
        new_document: dict[str, Any],
        replaces_logical_id: str,
    ) -> dict[str, Any]:
        body = validate_document_reference(new_document)
        body = document_reference_with_replaces(
            body, replaces_id=replaces_logical_id, replaces_type="DocumentReference"
        )
        return await self._repo.create(body)

    async def update_fhir(
        self, logical_id: str, resource: dict[str, Any]
    ) -> dict[str, Any]:
        body = validate_document_reference(resource)
        body["id"] = logical_id
        return await self._repo.update(logical_id, body)

    async def delete_fhir(self, logical_id: str) -> None:
        await self._repo.delete(logical_id)

    async def search_fhir(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._repo.search(params)
