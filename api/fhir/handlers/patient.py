"""Patient CRUD + internal DB sync + deduplication (Checklist #16)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.principal import AuthPrincipal
from api.fhir.crud import FhirResourceRepository
from api.fhir.mappers import (
    patient_dedup_fingerprint,
    patient_to_internal_fields,
    validate_patient,
)
from db.models.patient import Patient


class PatientFhirHandler:
    resource_type = "Patient"

    def __init__(self, repo: FhirResourceRepository) -> None:
        self._repo = repo

    async def read_fhir(self, logical_id: str) -> dict[str, Any]:
        return await self._repo.read(logical_id)

    async def create_fhir(self, resource: dict[str, Any]) -> dict[str, Any]:
        body = validate_patient(resource)
        return await self._repo.create(body)

    async def update_fhir(
        self, logical_id: str, resource: dict[str, Any]
    ) -> dict[str, Any]:
        body = validate_patient(resource)
        body["id"] = logical_id
        return await self._repo.update(logical_id, body)

    async def delete_fhir(self, logical_id: str) -> None:
        await self._repo.delete(logical_id)

    async def search_fhir(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._repo.search(params)

    async def find_duplicate_internal(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        fhir_patient: dict[str, Any],
    ) -> Optional[Patient]:
        fp = patient_dedup_fingerprint(fhir_patient)
        q = select(Patient).where(
            Patient.tenant_id == tenant_id,
            Patient.patient_metadata["fhir_dedup_fingerprint"].astext == fp,
        )
        row = (await db.execute(q)).scalar_one_or_none()
        if row is not None:
            return row
        fields = patient_to_internal_fields(fhir_patient)
        fn = (fields.get("first_name") or "").lower()
        ln = (fields.get("last_name") or "").lower()
        dob = fields.get("date_of_birth")
        if not fn or not ln or dob is None:
            return None
        q2 = select(Patient).where(
            Patient.tenant_id == tenant_id,
            Patient.date_of_birth == dob,
        )
        for cand in (await db.execute(q2)).scalars().all():
            cfn = (cand.first_name or "").lower()
            cln = (cand.last_name or "").lower()
            if cfn == fn and cln == ln:
                caddr = (cand.patient_metadata or {}).get("fhir_address") or {}
                faddr = (fields.get("patient_metadata") or {}).get("fhir_address") or {}
                if _addresses_equivalent(caddr, faddr):
                    return cand
        return None

    async def upsert_internal_from_fhir(
        self,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        principal: AuthPrincipal,
        fhir_patient: dict[str, Any],
    ) -> Patient:
        """
        Create or update ``Patient`` from a FHIR Patient resource (after validation).
        """
        body = validate_patient(fhir_patient)
        dup = await self.find_duplicate_internal(
            db, tenant_id=tenant_id, fhir_patient=body
        )
        fields = patient_to_internal_fields(body)
        actor = str(principal.user_id)
        if dup is not None:
            dup.fhir_patient_id = fields.get("fhir_patient_id") or dup.fhir_patient_id
            dup.first_name = fields.get("first_name") or dup.first_name
            dup.last_name = fields.get("last_name") or dup.last_name
            dup.date_of_birth = fields.get("date_of_birth") or dup.date_of_birth
            meta = dict(dup.patient_metadata or {})
            meta.update(fields.get("patient_metadata") or {})
            dup.patient_metadata = meta
            dup.updated_by = actor
            await db.flush()
            return dup

        p = Patient(
            tenant_id=tenant_id,
            mrn=fields["mrn"],
            fhir_patient_id=fields.get("fhir_patient_id"),
            first_name=fields.get("first_name"),
            last_name=fields.get("last_name"),
            date_of_birth=fields.get("date_of_birth"),
            patient_metadata=fields.get("patient_metadata") or {},
            created_by=actor,
            updated_by=actor,
        )
        db.add(p)
        await db.flush()
        return p


def _addresses_equivalent(a: dict[str, Any], b: dict[str, Any]) -> bool:
    def norm(d: dict[str, Any]) -> tuple[str, str, str, str]:
        line = " ".join(d.get("line") or [])
        return (
            line.lower().strip(),
            str(d.get("city") or "").lower().strip(),
            str(d.get("state") or "").lower().strip(),
            str(d.get("postalCode") or "").lower().strip(),
        )

    if not a and not b:
        return True
    return norm(a) == norm(b)
