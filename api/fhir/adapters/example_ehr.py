"""
Example EHR adapter for local HAPI FHIR demos.

This is a pluggable adapter shape for compatible EHR systems. The identifiers,
patient, and encounter below are synthetic and exist only for development.
"""

from __future__ import annotations

from typing import Any

from api.fhir.client import FhirRestClient


def get_example_ehr_demo_bundle() -> dict[str, Any]:
    """Synthetic Patient + Encounter transaction bundle for a local FHIR server."""
    patient_id = "healthos-example-ehr-patient-001"
    encounter_id = "healthos-example-ehr-encounter-001"
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{patient_id}",
                "resource": {
                    "resourceType": "Patient",
                    "id": patient_id,
                    "identifier": [
                        {
                            "system": "https://example-ehr.local/fhir/sid/patient",
                            "value": "EXAMPLE-DEMO-0001",
                        }
                    ],
                    "active": True,
                    "name": [
                        {
                            "use": "official",
                            "family": "Example",
                            "given": ["Sample"],
                        }
                    ],
                    "gender": "other",
                    "birthDate": "1985-04-12",
                    "address": [
                        {
                            "use": "home",
                            "line": ["1 Adapter Way"],
                            "city": "Austin",
                            "state": "TX",
                            "postalCode": "78701",
                            "country": "US",
                        }
                    ],
                },
                "request": {"method": "PUT", "url": f"Patient/{patient_id}"},
            },
            {
                "fullUrl": f"urn:uuid:{encounter_id}",
                "resource": {
                    "resourceType": "Encounter",
                    "id": encounter_id,
                    "status": "finished",
                    "class": {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                        "code": "AMB",
                        "display": "ambulatory",
                    },
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "period": {
                        "start": "2026-05-01T09:00:00Z",
                        "end": "2026-05-01T09:30:00Z",
                    },
                },
                "request": {"method": "PUT", "url": f"Encounter/{encounter_id}"},
            },
        ],
    }


def example_prior_auth_extension(status: str = "pending") -> dict[str, Any]:
    """FHIR extension dict for prior-auth tracking on ServiceRequest (demo)."""
    return {
        "url": "https://healthos.local/fhir/StructureDefinition/prior-auth-status",
        "valueString": status,
    }


async def post_example_ehr_demo_bundle(client: FhirRestClient) -> dict[str, Any]:
    """Upsert the synthetic Patient + Encounter via a transaction Bundle."""
    return await client.transaction(get_example_ehr_demo_bundle())


def attach_prior_auth_status(
    service_request: dict[str, Any], status: str
) -> dict[str, Any]:
    sr = dict(service_request)
    exts = list(sr.get("extension") or [])
    exts.append(example_prior_auth_extension(status))
    sr["extension"] = exts
    return sr
