"""
FHIR R4 integration layer (Checklist Section B).

Provides:
- HTTP client for a remote FHIR server (e.g. HAPI)
- Typed validation via ``fhir.resources``
- Resource handlers (Patient, Encounter, Condition, …)
- Pluggable adapters (generic HAPI, synthetic example EHR demo)
"""

from __future__ import annotations

from api.fhir.client import FhirRestClient, FhirRestError

__all__ = ["FhirRestClient", "FhirRestError"]
