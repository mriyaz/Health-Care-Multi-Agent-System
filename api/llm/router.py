"""
Tier-based LLM routing.

Maps product tiers from the PRD/checklist to concrete OpenRouter model IDs:

- **DEV** — lower-cost model for development and non-critical drafts.
- **PRODUCTION** — stronger model id for routine notes when you configure one.
- **DEMO** — model id you choose for polished local demos.

Actual model strings are environment-driven (``Settings.openrouter_model_*``) so you can align
them with whatever ids your OpenRouter plan supports.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from api.llm.openrouter_client import ChatCompletionResult, OpenRouterClient


class ModelTier(str, Enum):
    """Routing tier (semantic intent), not the literal vendor model name."""

    DEV = "dev"
    PRODUCTION = "production"
    DEMO = "demo"


class RoutedModel(BaseModel):
    """Resolved tier → OpenRouter ``model`` parameter."""

    tier: ModelTier
    model_id: str = Field(
        description="Value passed to OpenRouter chat completions API as ``model``."
    )
    label: str = Field(description="Human-readable tier label for logs and audits.")


class LLMModelRouter:
    """
    Selects an OpenRouter ``model`` id from tier + optional defaults on Settings.
    """

    def __init__(
        self,
        *,
        model_dev: str,
        model_production: str,
        model_demo: str,
    ) -> None:
        self._model_dev = model_dev
        self._model_production = model_production
        self._model_demo = model_demo

    def resolve(self, tier: ModelTier) -> RoutedModel:
        if tier is ModelTier.DEV:
            return RoutedModel(
                tier=tier,
                model_id=self._model_dev,
                label="dev_low_stakes",
            )
        if tier is ModelTier.PRODUCTION:
            return RoutedModel(
                tier=tier,
                model_id=self._model_production,
                label="production_notes",
            )
        return RoutedModel(
            tier=tier,
            model_id=self._model_demo,
            label="demo_quality",
        )

    async def run_chat(
        self,
        openrouter: OpenRouterClient,
        tier: ModelTier,
        messages: Sequence[Mapping[str, str]],
        *,
        task_type: str = "orchestrator",
        **kwargs: Any,
    ) -> ChatCompletionResult:
        """
        Resolve ``tier`` to an OpenRouter model id and call ``OpenRouterClient.chat_completion``.

        Intended for LangGraph nodes and services so routing rules stay in one place.
        ``task_type`` is forwarded to Langfuse as ``metadata.task_type`` for cost dashboards.
        """
        routed = self.resolve(tier)
        meta = {"model_tier": tier.value, "router_label": routed.label}
        extra_meta = kwargs.pop("langfuse_metadata", None)
        if isinstance(extra_meta, Mapping):
            meta.update(dict(extra_meta))
        return await openrouter.chat_completion(
            model=routed.model_id,
            messages=messages,
            langfuse_task_type=task_type,
            langfuse_metadata=meta,
            **kwargs,
        )
