"""
Langfuse client singleton + helpers for tracing OpenRouter HTTP completions.

Tracing is active only when ``Settings.langfuse_tracing_enabled`` is true (both
public and secret API keys set). Self-hosted URL defaults to ``http://localhost:3000``.
"""

from __future__ import annotations

from typing import Any, Mapping

from api.settings import Settings

_langfuse: Any | None = None


def get_langfuse(settings: Settings) -> Any | None:
    """
    Return a configured Langfuse client, or None when tracing is disabled.

    One client per process (singleton), keyed off the first enabled Settings load.
    """
    global _langfuse
    if not settings.langfuse_tracing_enabled:
        return None
    if _langfuse is None:
        from langfuse import Langfuse

        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.env.lower().replace(" ", "-")[:32],
            release=settings.service_version,
        )
    return _langfuse


def flush_langfuse(settings: Settings) -> None:
    """Flush queued spans before process exit (sync API)."""
    client = get_langfuse(settings)
    if client is None:
        return
    client.flush()


def usage_to_langfuse(usage: Mapping[str, Any] | None) -> dict[str, int]:
    """Map OpenAI-shaped usage dict to Langfuse ``usage_details`` integer fields."""
    if not usage:
        return {}
    out: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        raw = usage.get(key)
        if raw is not None:
            try:
                out[key] = int(raw)
            except (TypeError, ValueError):
                continue
    return out
