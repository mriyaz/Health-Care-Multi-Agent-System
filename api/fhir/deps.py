"""FastAPI dependencies for FHIR integration routes."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import Depends, Request

from api.fhir.client import FhirRestClient
from api.fhir.crud import FhirResourceRepository
from api.fhir.handlers.condition import ConditionFhirHandler
from api.fhir.handlers.document_reference import DocumentReferenceFhirHandler
from api.fhir.handlers.encounter import EncounterFhirHandler
from api.fhir.handlers.medication_request import MedicationRequestFhirHandler
from api.fhir.handlers.observation import ObservationFhirHandler
from api.fhir.handlers.patient import PatientFhirHandler
from api.fhir.handlers.service_request import ServiceRequestFhirHandler
from api.settings import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_fhir_rest_client(request: Request) -> FhirRestClient:
    settings: Settings = request.app.state.settings
    http: httpx.AsyncClient = request.app.state.fhir_http
    return FhirRestClient(
        base_url=str(settings.hapi_fhir_base_url).rstrip("/"),
        http=http,
    )


def get_patient_handler(
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
) -> PatientFhirHandler:
    return PatientFhirHandler(FhirResourceRepository(client, "Patient"))


def get_encounter_handler(
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
) -> EncounterFhirHandler:
    return EncounterFhirHandler(FhirResourceRepository(client, "Encounter"))


def get_condition_handler(
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
) -> ConditionFhirHandler:
    return ConditionFhirHandler(FhirResourceRepository(client, "Condition"))


def get_document_reference_handler(
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
) -> DocumentReferenceFhirHandler:
    return DocumentReferenceFhirHandler(
        FhirResourceRepository(client, "DocumentReference")
    )


def get_observation_handler(
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
) -> ObservationFhirHandler:
    return ObservationFhirHandler(FhirResourceRepository(client, "Observation"))


def get_medication_request_handler(
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
) -> MedicationRequestFhirHandler:
    return MedicationRequestFhirHandler(
        FhirResourceRepository(client, "MedicationRequest")
    )


def get_service_request_handler(
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
) -> ServiceRequestFhirHandler:
    return ServiceRequestFhirHandler(FhirResourceRepository(client, "ServiceRequest"))
