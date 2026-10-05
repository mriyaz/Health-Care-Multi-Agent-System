"""Adapter exports (synthetic example EHR demo bundle)."""

from __future__ import annotations

from api.fhir.adapters.example_ehr import (
    attach_prior_auth_status,
    example_prior_auth_extension,
    get_example_ehr_demo_bundle,
    post_example_ehr_demo_bundle,
)

__all__ = [
    "attach_prior_auth_status",
    "example_prior_auth_extension",
    "get_example_ehr_demo_bundle",
    "post_example_ehr_demo_bundle",
]
