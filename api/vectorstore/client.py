"""
Weaviate client factory for HealthOS.

Uses the official weaviate-client v4 sync client. FastAPI lifespan runs blocking
connect/setup in a thread pool (see api.main).
"""

from __future__ import annotations

import weaviate
from weaviate.classes.init import AdditionalConfig, Timeout

from api.settings import Settings


def open_weaviate_client(settings: Settings) -> weaviate.WeaviateClient:
    """
    Open a connection to Weaviate (REST + gRPC).

    Host/ports default to local Docker Compose: HTTP 8080, gRPC 50051.
    """
    return weaviate.connect_to_custom(
        http_host=settings.weaviate_http_host,
        http_port=settings.weaviate_http_port,
        http_secure=settings.weaviate_http_secure,
        grpc_host=settings.weaviate_grpc_host,
        grpc_port=settings.weaviate_grpc_port,
        grpc_secure=settings.weaviate_grpc_secure,
        skip_init_checks=settings.weaviate_skip_init_checks,
        additional_config=AdditionalConfig(
            timeout=Timeout(init=settings.weaviate_init_timeout_seconds),
        ),
    )


def close_weaviate_client(client: weaviate.WeaviateClient | None) -> None:
    if client is not None:
        client.close()


def ping_weaviate(client: weaviate.WeaviateClient | None) -> bool:
    if client is None:
        return False
    try:
        return bool(client.is_ready())
    except Exception:
        return False
