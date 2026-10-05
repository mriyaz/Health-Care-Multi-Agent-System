"""FHIR resource handlers (business logic on top of ``FhirResourceRepository``)."""

from __future__ import annotations

from api.fhir.handlers.patient import PatientFhirHandler
from api.fhir.handlers.encounter import EncounterFhirHandler
from api.fhir.handlers.condition import ConditionFhirHandler
from api.fhir.handlers.document_reference import DocumentReferenceFhirHandler
from api.fhir.handlers.observation import ObservationFhirHandler
from api.fhir.handlers.medication_request import MedicationRequestFhirHandler
from api.fhir.handlers.service_request import ServiceRequestFhirHandler

__all__ = [
    "PatientFhirHandler",
    "EncounterFhirHandler",
    "ConditionFhirHandler",
    "DocumentReferenceFhirHandler",
    "ObservationFhirHandler",
    "MedicationRequestFhirHandler",
    "ServiceRequestFhirHandler",
]
