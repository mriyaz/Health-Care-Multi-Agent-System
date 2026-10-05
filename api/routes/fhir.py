"""
FHIR integration HTTP API (Section B).

Proxies to the configured FHIR server (HAPI by default), validates payloads with
``fhir.resources``, and optionally mirrors Patient / Encounter into Postgres.
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

import httpx
from fastapi import (
    APIRouter,
    Body,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from pydantic import BaseModel, Field, ValidationError as PydanticV2ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth.deps import get_app_settings, require_roles
from api.auth.principal import AuthPrincipal
from api.deps import get_db
from api.fhir.adapters.example_ehr import post_example_ehr_demo_bundle
from api.fhir.client import FhirRestClient, FhirRestError
from api.fhir.deps import (
    get_condition_handler,
    get_document_reference_handler,
    get_encounter_handler,
    get_fhir_rest_client,
    get_medication_request_handler,
    get_observation_handler,
    get_patient_handler,
    get_service_request_handler,
)
from api.fhir.handlers.condition import ConditionFhirHandler
from api.fhir.handlers.document_reference import DocumentReferenceFhirHandler
from api.fhir.handlers.encounter import EncounterFhirHandler
from api.fhir.handlers.medication_request import MedicationRequestFhirHandler
from api.fhir.handlers.observation import ObservationFhirHandler
from api.fhir.handlers.patient import PatientFhirHandler
from api.fhir.handlers.service_request import ServiceRequestFhirHandler
from api.fhir.hl7v2 import (
    parse_pid_segment,
    pid_to_fhir_patient_draft,
    split_hl7_segments,
)
from api.fhir.smart import (
    build_authorize_url,
    exchange_authorization_code,
    fetch_smart_configuration,
)
from api.fhir.subscriptions import (
    subscription_rest_hook_resource,
    verify_subscription_webhook,
)
from api.settings import Settings
from db.enums import UserRole

try:
    from pydantic.v1.error_wrappers import (
        ValidationError as PydanticV1ValidationError,
    )
except ImportError:  # pragma: no cover
    PydanticV1ValidationError = PydanticV2ValidationError

FHIR_MODEL_PARSE_ERRORS = (PydanticV2ValidationError, PydanticV1ValidationError)

router = APIRouter(prefix="/integrations/fhir", tags=["FHIR R4"])

_read_roles = require_roles(
    UserRole.ADMIN,
    UserRole.CLINICIAN,
    UserRole.BILLER,
    UserRole.REVIEWER,
)
_write_roles = require_roles(UserRole.ADMIN, UserRole.CLINICIAN, UserRole.REVIEWER)


def _fhir_http_error(exc: FhirRestError) -> HTTPException:
    code = exc.status_code if 400 <= exc.status_code < 600 else 502
    return HTTPException(
        status_code=code, detail={"message": str(exc), "body": exc.body}
    )


def _validation_error(exc: BaseException) -> HTTPException:
    errors_fn = getattr(exc, "errors", None)
    detail = errors_fn() if callable(errors_fn) else str(exc)
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


@router.get("/metadata")
async def fhir_metadata(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
):
    try:
        return await client.metadata()
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.get("/smart/configuration")
async def smart_configuration(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    request: Request,
    issuer: str = Query(..., description="FHIR issuer base URL (EHR)"),
):
    try:
        return await fetch_smart_configuration(issuer, request.app.state.fhir_http)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/smart/authorize-url")
async def smart_authorize_url(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    request: Request,
    issuer: str = Query(...),
    scope: str = Query(default="launch/patient patient/*.read offline_access"),
    state: str = Query(default="healthos-smart-state"),
):
    if not settings.smart_client_id or not settings.smart_redirect_uri:
        raise HTTPException(
            status_code=503,
            detail="Configure SMART_CLIENT_ID and SMART_REDIRECT_URI",
        )
    cfg = await fetch_smart_configuration(issuer, request.app.state.fhir_http)
    authz = cfg.get("authorization_endpoint")
    if not isinstance(authz, str) or not authz:
        raise HTTPException(
            status_code=502,
            detail="SMART configuration missing authorization_endpoint",
        )
    url = build_authorize_url(
        authorize_endpoint=authz,
        client_id=settings.smart_client_id,
        redirect_uri=settings.smart_redirect_uri,
        scope=scope,
        state=state,
        aud=issuer,
    )
    return {"authorize_url": url, "smart_configuration": cfg}


class SmartTokenExchangeIn(BaseModel):
    token_endpoint: str
    code: str


@router.post("/smart/token")
async def smart_token_exchange(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    request: Request,
    body: SmartTokenExchangeIn,
):
    if not settings.smart_client_id or not settings.smart_redirect_uri:
        raise HTTPException(
            status_code=503,
            detail="Configure SMART_CLIENT_ID and SMART_REDIRECT_URI",
        )
    try:
        return await exchange_authorization_code(
            token_endpoint=body.token_endpoint,
            client_id=settings.smart_client_id,
            client_secret=settings.smart_client_secret,
            redirect_uri=settings.smart_redirect_uri,
            code=body.code,
            http=request.app.state.fhir_http,
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=e.response.text) from e


# ---- Patient ----


@router.get("/Patient/{logical_id}")
async def get_patient(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[PatientFhirHandler, Depends(get_patient_handler)],
    logical_id: str,
):
    try:
        return await h.read_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/Patient")
async def post_patient(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[PatientFhirHandler, Depends(get_patient_handler)],
    resource: dict[str, Any],
):
    try:
        return await h.create_fhir(resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.put("/Patient/{logical_id}")
async def put_patient(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[PatientFhirHandler, Depends(get_patient_handler)],
    logical_id: str,
    resource: dict[str, Any],
):
    try:
        return await h.update_fhir(logical_id, resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.delete("/Patient/{logical_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_patient(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[PatientFhirHandler, Depends(get_patient_handler)],
    logical_id: str,
):
    try:
        await h.delete_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.get("/Patient")
async def search_patient(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[PatientFhirHandler, Depends(get_patient_handler)],
    request: Request,
):
    params = dict(request.query_params)
    try:
        return await h.search_fhir(params)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/internal/patients/sync/{fhir_patient_id}")
async def sync_patient_internal(
    principal: Annotated[AuthPrincipal, Depends(_write_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
    h: Annotated[PatientFhirHandler, Depends(get_patient_handler)],
    fhir_patient_id: str,
):
    try:
        remote = await h.read_fhir(fhir_patient_id)
        row = await h.upsert_internal_from_fhir(
            db, tenant_id=principal.tenant_id, principal=principal, fhir_patient=remote
        )
        await db.commit()
        return {
            "internal_patient_id": str(row.id),
            "fhir_patient_id": row.fhir_patient_id,
        }
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---- Encounter ----


@router.get("/Encounter/{logical_id}")
async def get_encounter(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[EncounterFhirHandler, Depends(get_encounter_handler)],
    logical_id: str,
):
    try:
        return await h.read_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/Encounter")
async def post_encounter(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[EncounterFhirHandler, Depends(get_encounter_handler)],
    resource: dict[str, Any],
):
    try:
        return await h.create_fhir(resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.put("/Encounter/{logical_id}")
async def put_encounter(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[EncounterFhirHandler, Depends(get_encounter_handler)],
    logical_id: str,
    resource: dict[str, Any],
):
    try:
        return await h.update_fhir(logical_id, resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.delete("/Encounter/{logical_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_encounter(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[EncounterFhirHandler, Depends(get_encounter_handler)],
    logical_id: str,
):
    try:
        await h.delete_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.get("/Encounter")
async def search_encounter(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[EncounterFhirHandler, Depends(get_encounter_handler)],
    request: Request,
):
    try:
        return await h.search_fhir(dict(request.query_params))
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/internal/encounters/sync/{fhir_encounter_id}")
async def sync_encounter_internal(
    principal: Annotated[AuthPrincipal, Depends(_write_roles)],
    db: Annotated[AsyncSession, Depends(get_db)],
    h: Annotated[EncounterFhirHandler, Depends(get_encounter_handler)],
    fhir_encounter_id: str,
):
    try:
        remote = await h.read_fhir(fhir_encounter_id)
        row = await h.upsert_internal_from_fhir(
            db,
            tenant_id=principal.tenant_id,
            principal=principal,
            fhir_encounter=remote,
        )
        await db.commit()
        return {
            "internal_encounter_id": str(row.id),
            "fhir_encounter_id": row.fhir_encounter_id,
        }
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ---- Condition ----


@router.get("/Condition/{logical_id}")
async def get_condition(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[ConditionFhirHandler, Depends(get_condition_handler)],
    logical_id: str,
):
    try:
        return await h.read_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/Condition")
async def post_condition(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[ConditionFhirHandler, Depends(get_condition_handler)],
    resource: dict[str, Any],
):
    try:
        return await h.create_fhir(resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.put("/Condition/{logical_id}")
async def put_condition(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[ConditionFhirHandler, Depends(get_condition_handler)],
    logical_id: str,
    resource: dict[str, Any],
):
    try:
        return await h.update_fhir(logical_id, resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.delete("/Condition/{logical_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_condition(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[ConditionFhirHandler, Depends(get_condition_handler)],
    logical_id: str,
):
    try:
        await h.delete_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.get("/Condition")
async def search_condition(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[ConditionFhirHandler, Depends(get_condition_handler)],
    request: Request,
):
    try:
        return await h.search_fhir(dict(request.query_params))
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


# ---- DocumentReference ----


@router.get("/DocumentReference/{logical_id}")
async def get_document_reference(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[DocumentReferenceFhirHandler, Depends(get_document_reference_handler)],
    logical_id: str,
):
    try:
        return await h.read_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/DocumentReference")
async def post_document_reference(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[DocumentReferenceFhirHandler, Depends(get_document_reference_handler)],
    resource: dict[str, Any],
):
    try:
        return await h.create_fhir(resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


class DocumentReferenceSupersedeIn(BaseModel):
    resource: dict[str, Any]
    replaces_logical_id: str = Field(..., min_length=1)


@router.post("/DocumentReference/supersede")
async def post_document_reference_supersede(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[DocumentReferenceFhirHandler, Depends(get_document_reference_handler)],
    body: DocumentReferenceSupersedeIn,
):
    try:
        return await h.create_superseding_version(
            new_document=body.resource,
            replaces_logical_id=body.replaces_logical_id,
        )
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.put("/DocumentReference/{logical_id}")
async def put_document_reference(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[DocumentReferenceFhirHandler, Depends(get_document_reference_handler)],
    logical_id: str,
    resource: dict[str, Any],
):
    try:
        return await h.update_fhir(logical_id, resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.delete(
    "/DocumentReference/{logical_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document_reference(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[DocumentReferenceFhirHandler, Depends(get_document_reference_handler)],
    logical_id: str,
):
    try:
        await h.delete_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.get("/DocumentReference")
async def search_document_reference(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[DocumentReferenceFhirHandler, Depends(get_document_reference_handler)],
    request: Request,
):
    try:
        return await h.search_fhir(dict(request.query_params))
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


# ---- Observation ----


@router.get("/Observation/{logical_id}")
async def get_observation(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[ObservationFhirHandler, Depends(get_observation_handler)],
    logical_id: str,
):
    try:
        return await h.read_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/Observation")
async def post_observation(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[ObservationFhirHandler, Depends(get_observation_handler)],
    resource: dict[str, Any],
):
    try:
        return await h.create_fhir(resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.put("/Observation/{logical_id}")
async def put_observation(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[ObservationFhirHandler, Depends(get_observation_handler)],
    logical_id: str,
    resource: dict[str, Any],
):
    try:
        return await h.update_fhir(logical_id, resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.delete("/Observation/{logical_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_observation(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[ObservationFhirHandler, Depends(get_observation_handler)],
    logical_id: str,
):
    try:
        await h.delete_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.get("/Observation")
async def search_observation(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[ObservationFhirHandler, Depends(get_observation_handler)],
    request: Request,
):
    try:
        return await h.search_fhir(dict(request.query_params))
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


# ---- MedicationRequest (P1 draft-only writes) ----


@router.get("/MedicationRequest/{logical_id}")
async def get_medication_request(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[MedicationRequestFhirHandler, Depends(get_medication_request_handler)],
    logical_id: str,
):
    try:
        return await h.read_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/MedicationRequest")
async def post_medication_request(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[MedicationRequestFhirHandler, Depends(get_medication_request_handler)],
    resource: dict[str, Any],
):
    try:
        return await h.create_fhir_draft_only(resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.put("/MedicationRequest/{logical_id}")
async def put_medication_request(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[MedicationRequestFhirHandler, Depends(get_medication_request_handler)],
    logical_id: str,
    resource: dict[str, Any],
):
    try:
        return await h.update_fhir(logical_id, resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.get("/MedicationRequest")
async def search_medication_request(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[MedicationRequestFhirHandler, Depends(get_medication_request_handler)],
    request: Request,
):
    try:
        return await h.search_fhir(dict(request.query_params))
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


# ---- ServiceRequest (P1) ----


@router.get("/ServiceRequest/{logical_id}")
async def get_service_request(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[ServiceRequestFhirHandler, Depends(get_service_request_handler)],
    logical_id: str,
):
    try:
        return await h.read_fhir(logical_id)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


@router.post("/ServiceRequest")
async def post_service_request(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[ServiceRequestFhirHandler, Depends(get_service_request_handler)],
    resource: dict[str, Any],
):
    try:
        return await h.create_fhir(resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.put("/ServiceRequest/{logical_id}")
async def put_service_request(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    h: Annotated[ServiceRequestFhirHandler, Depends(get_service_request_handler)],
    logical_id: str,
    resource: dict[str, Any],
):
    try:
        return await h.update_fhir(logical_id, resource)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e
    except FHIR_MODEL_PARSE_ERRORS as e:
        raise _validation_error(e) from e


@router.get("/ServiceRequest")
async def search_service_request(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    h: Annotated[ServiceRequestFhirHandler, Depends(get_service_request_handler)],
    request: Request,
):
    try:
        return await h.search_fhir(dict(request.query_params))
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


# ---- Example EHR adapter demo (synthetic local data only) ----


@router.post("/adapters/example-ehr/demo-bundle")
async def example_ehr_demo_bundle(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
):
    try:
        return await post_example_ehr_demo_bundle(client)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


# ---- Subscriptions webhook (no JWT; shared secret header) ----


@router.post("/webhooks/subscription")
async def fhir_subscription_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    x_fhir_webhook_secret: Annotated[
        Optional[str], Header(alias="X-FHIR-Webhook-Secret")
    ] = None,
    payload: dict[str, Any] = Body(default_factory=dict),
):
    verify_subscription_webhook(settings.fhir_webhook_secret, x_fhir_webhook_secret)
    # Placeholder: orchestrator would enqueue on Encounter/Patient payloads.
    return {"received": True, "resourceType": payload.get("resourceType")}


@router.post("/subscriptions/encounter-in-progress")
async def register_encounter_subscription(
    _: Annotated[AuthPrincipal, Depends(_write_roles)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    client: Annotated[FhirRestClient, Depends(get_fhir_rest_client)],
):
    if not settings.fhir_webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="Set FHIR_WEBHOOK_SECRET to register a rest-hook Subscription",
        )
    callback = (
        f"{settings.healthos_public_base_url.rstrip('/')}"
        "/integrations/fhir/webhooks/subscription"
    )
    sub = subscription_rest_hook_resource(
        criteria="Encounter?status=in-progress",
        callback_url=callback,
        webhook_secret=settings.fhir_webhook_secret,
    )
    try:
        return await client.create("Subscription", sub)
    except FhirRestError as e:
        raise _fhir_http_error(e) from e


# ---- HL7 v2 (P2 minimal) ----


@router.post("/hl7v2/parse-pid")
async def hl7v2_parse_pid(
    _: Annotated[AuthPrincipal, Depends(_read_roles)],
    message: str = Body(..., media_type="text/plain"),
):
    segments = split_hl7_segments(message)
    pid_seg = next((s for s in segments if s.startswith("PID|")), None)
    if not pid_seg:
        raise HTTPException(status_code=400, detail="No PID segment found")
    parsed = parse_pid_segment(pid_seg)
    draft_patient = pid_to_fhir_patient_draft(parsed)
    return {"parsed_pid": parsed.__dict__, "fhir_patient_draft": draft_patient}
