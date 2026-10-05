"""Encounter CRUD + link to internal Patient / Encounter (Checklist #17)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import AuthPrincipal
from api.fhir.crud import FhirResourceRepository
from api.fhir.mappers import (
    encounter_period_to_datetimes,
    encounter_to_internal_metadata,
    fhir_encounter_status_to_internal,
    validate_encounter,
)
from db.models.encounter import Encounter
from db.models.patient import Patient


class EncounterFhirHandler:
    resource_type = "Encounter"

    def __init__(self, repo: FhirResourceRepository) -> None:
        self._repo = repo

    async def read_fhir(self, logical_id: str) -> dict[str, Any]:
        return await self._repo.read(logical_id)

    async def create_fhir(self, resource: dict[str, Any]) -> dict[str, Any]:
        body = validate_encounter(resource)
        return await self._repo.create(body)

    async def update_fhir(
        self, logical_id: str, resource: dict[str, Any]
    ) -> dict[str, Any]:
        body = validate_encounter(resource)
        body["id"] = logical_id
        return await self._repo.update(logical_id, body)

    async def delete_fhir(self, logical_id: str) -> None:
        await self._repo.delete(logical_id)

    async def search_fhir(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._repo.search(params)

    @staticmethod
    def _patient_ref(enc: dict[str, Any]) -> Optional[str]:
        subj = enc.get("subject") or {}
        ref = subj.get("reference")
        if not isinstance(ref, str) or "/" not in ref:
            return None
        rt, eid = ref.split("/", 1)
        if rt != "Patient":
            return None
        return eid

    async def upsert_internal_from_fhir(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        principal: AuthPrincipal,
        fhir_encounter: dict[str, Any],
    ) -> Encounter:
        body = validate_encounter(fhir_encounter)
        pid = self._patient_ref(body)
        if not pid:
            raise ValueError("Encounter.subject must reference Patient/{id}")
        prow = (
            await db.execute(
                select(Patient).where(
                    Patient.tenant_id == tenant_id,
                    Patient.fhir_patient_id == pid,
                )
            )
        ).scalar_one_or_none()
        if prow is None:
            raise ValueError(f"No internal Patient with fhir_patient_id={pid!r}")

        eid = str(body.get("id") or "")
        existing: Encounter | None = None
        if eid:
            existing = (
                await db.execute(
                    select(Encounter).where(
                        Encounter.tenant_id == tenant_id,
                        Encounter.fhir_encounter_id == eid,
                    )
                )
            ).scalar_one_or_none()

        status = fhir_encounter_status_to_internal(body.get("status"))
        started, ended = encounter_period_to_datetimes(body)
        meta = encounter_to_internal_metadata(body)
        actor = str(principal.user_id)

        if existing:
            existing.patient_id = prow.id
            existing.status = status
            existing.started_at = started or existing.started_at
            existing.ended_at = ended or existing.ended_at
            m = dict(existing.encounter_metadata or {})
            m.update(meta)
            existing.encounter_metadata = m
            existing.updated_by = actor
            await db.flush()
            return existing

        enc = Encounter(
            tenant_id=tenant_id,
            patient_id=prow.id,
            fhir_encounter_id=eid or None,
            status=status,
            started_at=started,
            ended_at=ended,
            encounter_metadata=meta,
            created_by=actor,
            updated_by=actor,
        )
        db.add(enc)
        await db.flush()
        return enc
