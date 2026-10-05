"""
LLM integration: OpenRouter (OpenAI-compatible chat completions) + tier-based routing.

PRD checklist P0#7–8 are satisfied here using OpenRouter-hosted models (see ``ModelTier``).
"""

from api.llm.openrouter_client import ChatCompletionResult, OpenRouterClient
from api.llm.router import LLMModelRouter, ModelTier

__all__ = [
    "ChatCompletionResult",
    "OpenRouterClient",
    "LLMModelRouter",
    "ModelTier",
]
