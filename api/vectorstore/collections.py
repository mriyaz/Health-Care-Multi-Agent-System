"""
Weaviate collection definitions for HealthOS.

Three collections (checklist P0#6), with property names aligned to FHIR R4
concepts so payloads can mirror or link to FHIR resources without storing
full server state in Weaviate.

- clinical_knowledge: Library / Citation / PlanDefinition-style artifacts + narrative chunks.
- payer_rules: Organization + Coverage / policy narrative (LCD/NCD/payer policy text).
- patient_summaries: Patient + Composition-oriented longitudinal summaries.

Vectorizer is disabled in Docker (DEFAULT_VECTORIZER_MODULE=none); use
``Configure.Vectors.self_provided()`` and attach embedding vectors at index time.
"""

from __future__ import annotations

import weaviate
from weaviate.classes.config import Configure, DataType, Property

CLINICAL_KNOWLEDGE = "clinical_knowledge"
PAYER_RULES = "payer_rules"
PATIENT_SUMMARIES = "patient_summaries"


def _clinical_knowledge_properties() -> list[Property]:
    return [
        Property(
            name="tenant_id",
            data_type=DataType.TEXT,
            description="HealthOS tenant scope",
        ),
        Property(
            name="knowledge_kind",
            data_type=DataType.TEXT,
            description="guideline | pathway | formulary | terminology | other",
        ),
        Property(name="title", data_type=DataType.TEXT),
        Property(
            name="narrative_chunk",
            data_type=DataType.TEXT,
            description="Chunk for BM25/hybrid search; pair with BYO embedding vector",
        ),
        Property(name="keywords", data_type=DataType.TEXT_ARRAY),
        Property(
            name="fhir_resource_type",
            data_type=DataType.TEXT,
            description="Library | Citation | PlanDefinition | ActivityDefinition | EvidenceVariable | ...",
        ),
        Property(name="fhir_logical_id", data_type=DataType.TEXT),
        Property(name="fhir_version_id", data_type=DataType.TEXT),
        Property(name="canonical_url", data_type=DataType.TEXT),
        Property(name="related_icd10_codes", data_type=DataType.TEXT_ARRAY),
        Property(name="related_snomed_codes", data_type=DataType.TEXT_ARRAY),
        Property(name="source_uri", data_type=DataType.TEXT),
        Property(name="last_reviewed_iso", data_type=DataType.TEXT),
        Property(
            name="fhir_resource_json",
            data_type=DataType.TEXT,
            description="Optional JSON subset of the FHIR resource for round-trip / provenance",
        ),
    ]


def _payer_rules_properties() -> list[Property]:
    return [
        Property(name="tenant_id", data_type=DataType.TEXT),
        Property(
            name="payer_org_identifier",
            data_type=DataType.TEXT,
            description="FHIR Organization.identifier value or payer slug",
        ),
        Property(
            name="rule_kind",
            data_type=DataType.TEXT,
            description="LCD | NCD | payer_policy | article",
        ),
        Property(name="policy_identifier", data_type=DataType.TEXT),
        Property(name="title", data_type=DataType.TEXT),
        Property(
            name="rule_narrative",
            data_type=DataType.TEXT,
            description="LCD/article/policy text chunk for retrieval",
        ),
        Property(name="cpt_codes", data_type=DataType.TEXT_ARRAY),
        Property(name="icd10_codes", data_type=DataType.TEXT_ARRAY),
        Property(name="modifiers", data_type=DataType.TEXT_ARRAY),
        Property(name="effective_from_iso", data_type=DataType.TEXT),
        Property(name="effective_to_iso", data_type=DataType.TEXT),
        Property(name="jurisdiction", data_type=DataType.TEXT),
        Property(name="cms_lcd_id", data_type=DataType.TEXT),
        Property(
            name="fhir_rule_resource_json",
            data_type=DataType.TEXT,
            description="JSON: e.g. ChargeItemDefinition / InsurancePlan / related Organization snippets",
        ),
    ]


def _patient_summaries_properties() -> list[Property]:
    return [
        Property(name="tenant_id", data_type=DataType.TEXT),
        Property(
            name="patient_fhir_reference",
            data_type=DataType.TEXT,
            description="FHIR reference e.g. Patient/{id}",
        ),
        Property(
            name="patient_internal_uuid",
            data_type=DataType.TEXT,
            description="HealthOS internal patient UUID when mirrored from Postgres",
        ),
        Property(
            name="encounter_fhir_references_json",
            data_type=DataType.TEXT,
            description='JSON array of strings e.g. ["Encounter/abc","Encounter/def"]',
        ),
        Property(
            name="composition_status",
            data_type=DataType.TEXT,
            description="preliminary | final | entered-in-error | amended (Composition.status)",
        ),
        Property(name="summary_title", data_type=DataType.TEXT),
        Property(
            name="summary_narrative",
            data_type=DataType.TEXT,
            description="Human-readable summary body for retrieval",
        ),
        Property(name="date_asserted_iso", data_type=DataType.TEXT),
        Property(
            name="confidentiality_norm",
            data_type=DataType.TEXT,
            description="Composition.confidentiality normalized label (e.g. N)",
        ),
        Property(
            name="condition_fhir_references_json",
            data_type=DataType.TEXT,
            description="JSON array of Condition/{id} supporting the summary",
        ),
        Property(
            name="fhir_composition_json",
            data_type=DataType.TEXT,
            description="Optional FHIR Composition (or Bundle) JSON subset",
        ),
    ]


def ensure_healthos_collections(client: weaviate.WeaviateClient) -> None:
    """
    Create the three MVP collections if they are missing. Idempotent.
    """
    vector_cfg = Configure.Vectors.self_provided()

    specs: list[tuple[str, str, list[Property]]] = [
        (
            CLINICAL_KNOWLEDGE,
            "Guidelines and clinical knowledge chunks (FHIR Library/Citation/PlanDefinition-aligned).",
            _clinical_knowledge_properties(),
        ),
        (
            PAYER_RULES,
            "Payer LCD/NCD/policy chunks (FHIR Organization/Coverage-aligned identifiers).",
            _payer_rules_properties(),
        ),
        (
            PATIENT_SUMMARIES,
            "Per-patient narrative summaries (FHIR Patient + Composition-aligned).",
            _patient_summaries_properties(),
        ),
    ]

    for name, description, properties in specs:
        if client.collections.exists(name):
            continue
        client.collections.create(
            name=name,
            description=description,
            vector_config=vector_cfg,
            properties=properties,
        )
