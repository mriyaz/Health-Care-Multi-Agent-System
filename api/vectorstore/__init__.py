"""Weaviate-backed vector collections for HealthOS RAG (clinical knowledge, payer rules, summaries)."""

from api.vectorstore.client import (
    close_weaviate_client,
    open_weaviate_client,
    ping_weaviate,
)
from api.vectorstore.collections import (
    CLINICAL_KNOWLEDGE,
    PAYER_RULES,
    PATIENT_SUMMARIES,
    ensure_healthos_collections,
)

__all__ = [
    "CLINICAL_KNOWLEDGE",
    "PAYER_RULES",
    "PATIENT_SUMMARIES",
    "close_weaviate_client",
    "ensure_healthos_collections",
    "open_weaviate_client",
    "ping_weaviate",
]
