"""
Seed the local HAPI FHIR R4 server with synthetic demo resources.

All included patient and clinical examples are synthetic and are provided
solely for development and demonstration.

This script is intentionally standalone: it prepares the FHIR test server for
local development without coupling test data creation to FastAPI startup.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8082/fhir"
FHIR_HEADERS = {
    "Accept": "application/fhir+json",
    "Content-Type": "application/fhir+json",
}


def _patient(
    *,
    index: int,
    family: str,
    given: list[str],
    gender: str,
    birth_date: str,
    city: str,
    state: str,
    postal_code: str,
) -> dict[str, Any]:
    patient_id = f"healthos-sample-patient-{index:03d}"
    return {
        "resourceType": "Patient",
        "id": patient_id,
        "identifier": [
            {
                "system": "https://healthos.local/fhir/synthetic/mrn",
                "value": f"HOS-DEMO-{index:03d}",
            }
        ],
        "active": True,
        "name": [{"use": "official", "family": family, "given": given}],
        "gender": gender,
        "birthDate": birth_date,
        "address": [
            {
                "use": "home",
                "line": [f"{100 + index} Demo Lane"],
                "city": city,
                "state": state,
                "postalCode": postal_code,
                "country": "US",
            }
        ],
    }


def _encounter(
    *,
    index: int,
    patient_id: str,
    reason: str,
    start: str,
    end: str,
) -> dict[str, Any]:
    encounter_id = f"healthos-sample-encounter-{index:03d}"
    return {
        "resourceType": "Encounter",
        "id": encounter_id,
        "identifier": [
            {
                "system": "https://healthos.local/fhir/synthetic/encounter",
                "value": f"HOS-ENC-{index:03d}",
            }
        ],
        "status": "finished",
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": "AMB",
            "display": "ambulatory",
        },
        "type": [
            {
                "coding": [
                    {
                        "system": "http://snomed.info/sct",
                        "code": "185349003",
                        "display": "Encounter for check up",
                    }
                ],
                "text": reason,
            }
        ],
        "subject": {"reference": f"Patient/{patient_id}"},
        "period": {"start": start, "end": end},
        "reasonCode": [{"text": reason}],
    }


def _condition(
    *,
    index: int,
    patient_id: str,
    encounter_id: str,
    icd10_code: str,
    display: str,
    clinical_status: str,
    recorded_date: str,
) -> dict[str, Any]:
    condition_id = f"healthos-sample-condition-{index:03d}"
    return {
        "resourceType": "Condition",
        "id": condition_id,
        "clinicalStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
                    "code": clinical_status,
                }
            ]
        },
        "verificationStatus": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
                    "code": "confirmed",
                }
            ]
        },
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                        "code": "encounter-diagnosis",
                        "display": "Encounter Diagnosis",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {
                    "system": "http://hl7.org/fhir/sid/icd-10-cm",
                    "code": icd10_code,
                    "display": display,
                }
            ],
            "text": display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "encounter": {"reference": f"Encounter/{encounter_id}"},
        "recordedDate": recorded_date,
    }


def build_sample_resources() -> list[dict[str, Any]]:
    """Return 5 Patient + Encounter + Condition resource sets."""
    patients = [
        _patient(
            index=1,
            family="Carter",
            given=["Avery"],
            gender="female",
            birth_date="1984-03-12",
            city="Austin",
            state="TX",
            postal_code="78701",
        ),
        _patient(
            index=2,
            family="Nguyen",
            given=["Jordan"],
            gender="male",
            birth_date="1976-08-24",
            city="Seattle",
            state="WA",
            postal_code="98101",
        ),
        _patient(
            index=3,
            family="Patel",
            given=["Mira"],
            gender="female",
            birth_date="1991-11-05",
            city="Chicago",
            state="IL",
            postal_code="60601",
        ),
        _patient(
            index=4,
            family="Robinson",
            given=["Elliot"],
            gender="male",
            birth_date="1968-01-30",
            city="Atlanta",
            state="GA",
            postal_code="30303",
        ),
        _patient(
            index=5,
            family="Williams",
            given=["Samira"],
            gender="female",
            birth_date="1959-06-18",
            city="Denver",
            state="CO",
            postal_code="80202",
        ),
    ]
    encounters = [
        _encounter(
            index=1,
            patient_id="healthos-sample-patient-001",
            reason="Hypertension follow-up",
            start="2026-05-01T09:00:00-05:00",
            end="2026-05-01T09:30:00-05:00",
        ),
        _encounter(
            index=2,
            patient_id="healthos-sample-patient-002",
            reason="Type 2 diabetes medication review",
            start="2026-05-02T10:00:00-07:00",
            end="2026-05-02T10:35:00-07:00",
        ),
        _encounter(
            index=3,
            patient_id="healthos-sample-patient-003",
            reason="Asthma symptom review",
            start="2026-05-03T14:00:00-05:00",
            end="2026-05-03T14:25:00-05:00",
        ),
        _encounter(
            index=4,
            patient_id="healthos-sample-patient-004",
            reason="Lower back pain assessment",
            start="2026-05-04T08:30:00-04:00",
            end="2026-05-04T09:05:00-04:00",
        ),
        _encounter(
            index=5,
            patient_id="healthos-sample-patient-005",
            reason="Heart failure follow-up",
            start="2026-05-05T11:00:00-06:00",
            end="2026-05-05T11:40:00-06:00",
        ),
    ]
    conditions = [
        _condition(
            index=1,
            patient_id="healthos-sample-patient-001",
            encounter_id="healthos-sample-encounter-001",
            icd10_code="I10",
            display="Essential (primary) hypertension",
            clinical_status="active",
            recorded_date="2026-05-01",
        ),
        _condition(
            index=2,
            patient_id="healthos-sample-patient-002",
            encounter_id="healthos-sample-encounter-002",
            icd10_code="E11.9",
            display="Type 2 diabetes mellitus without complications",
            clinical_status="active",
            recorded_date="2026-05-02",
        ),
        _condition(
            index=3,
            patient_id="healthos-sample-patient-003",
            encounter_id="healthos-sample-encounter-003",
            icd10_code="J45.909",
            display="Unspecified asthma, uncomplicated",
            clinical_status="active",
            recorded_date="2026-05-03",
        ),
        _condition(
            index=4,
            patient_id="healthos-sample-patient-004",
            encounter_id="healthos-sample-encounter-004",
            icd10_code="M54.50",
            display="Low back pain, unspecified",
            clinical_status="active",
            recorded_date="2026-05-04",
        ),
        _condition(
            index=5,
            patient_id="healthos-sample-patient-005",
            encounter_id="healthos-sample-encounter-005",
            icd10_code="I50.9",
            display="Heart failure, unspecified",
            clinical_status="active",
            recorded_date="2026-05-05",
        ),
    ]
    return [*patients, *encounters, *conditions]


def candidate_base_urls(raw_base_url: str) -> list[str]:
    """Try both the supplied URL and the common HAPI /fhir base path."""
    base = raw_base_url.rstrip("/")
    candidates = [base]
    if not base.endswith("/fhir"):
        candidates.append(f"{base}/fhir")
    else:
        candidates.append(base.removesuffix("/fhir"))
    return list(dict.fromkeys(candidates))


async def resolve_fhir_base_url(client: httpx.AsyncClient, raw_base_url: str) -> str:
    for base_url in candidate_base_urls(raw_base_url):
        try:
            response = await client.get(f"{base_url}/metadata", headers=FHIR_HEADERS)
            response.raise_for_status()
        except httpx.HTTPError:
            continue
        capability = response.json()
        if capability.get("resourceType") == "CapabilityStatement":
            fhir_version = str(capability.get("fhirVersion", ""))
            if fhir_version and not fhir_version.startswith("4."):
                print(
                    f"Warning: HAPI server reports FHIR version {fhir_version}, expected R4."
                )
            return base_url
    raise RuntimeError(
        f"Could not find a FHIR endpoint at {raw_base_url!r}. "
        "Try --base-url http://localhost:8082/fhir after confirming HAPI is running."
    )


async def upsert_resource(
    client: httpx.AsyncClient,
    base_url: str,
    resource: dict[str, Any],
) -> tuple[str, str, int]:
    resource_type = str(resource["resourceType"])
    resource_id = str(resource["id"])
    response = await client.put(
        f"{base_url}/{resource_type}/{resource_id}",
        headers=FHIR_HEADERS,
        json=resource,
    )
    response.raise_for_status()
    return resource_type, resource_id, response.status_code


async def seed(base_url: str) -> None:
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resolved_base_url = await resolve_fhir_base_url(client, base_url)
        print(f"Using FHIR base URL: {resolved_base_url}")

        counts: dict[str, int] = {}
        for resource in build_sample_resources():
            resource_type, resource_id, status_code = await upsert_resource(
                client,
                resolved_base_url,
                resource,
            )
            counts[resource_type] = counts.get(resource_type, 0) + 1
            print(f"Upserted {resource_type}/{resource_id} ({status_code})")

    print(
        "Seed complete: "
        f"{counts.get('Patient', 0)} Patients, "
        f"{counts.get('Encounter', 0)} Encounters, "
        f"{counts.get('Condition', 0)} Conditions."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("HAPI_FHIR_BASE_URL", DEFAULT_BASE_URL),
        help=f"HAPI FHIR base URL. Defaults to HAPI_FHIR_BASE_URL or {DEFAULT_BASE_URL}.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(seed(args.base_url))


if __name__ == "__main__":
    main()
