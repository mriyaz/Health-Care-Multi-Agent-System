"""
Development helpers for P0 LLM smoke tests.

Mounted only when playground endpoints are allowed (local/dev env or ``LLM_PLAYGROUND_ENABLED``).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.auth.deps import require_roles
from api.llm.router import LLMModelRouter, ModelTier
from db.enums import UserRole

router = APIRouter(
    prefix="/llm",
    tags=["llm"],
    dependencies=[Depends(require_roles(UserRole.ADMIN, UserRole.CLINICIAN))],
)


class InferRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=16_000)
    tier: Literal["dev", "production", "demo"] = "dev"
    system: str | None = Field(
        default=None,
        max_length=8_000,
        description="Optional system message; defaults to a neutral assistant prompt.",
    )


class InferResponse(BaseModel):
    reply: str
    tier: str
    model_requested: str
    model_reported: str | None = None
    usage: dict | None = None


class RouterMapResponse(BaseModel):
    """Shows how tiers map to OpenRouter ``model`` ids from Settings (no external API call)."""

    dev: str
    production: str
    demo: str


def _require_playground(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.llm_playground_allowed:
        raise HTTPException(
            status_code=403, detail="LLM playground endpoints are disabled."
        )


def _router_from_settings(request: Request) -> LLMModelRouter:
    s = request.app.state.settings
    return LLMModelRouter(
        model_dev=s.openrouter_model_dev,
        model_production=s.openrouter_model_production,
        model_demo=s.openrouter_model_demo,
    )


@router.get("/models", response_model=RouterMapResponse)
async def list_router_models(request: Request) -> RouterMapResponse:
    """
    Return configured tier → model id mapping (reads env only; does not call OpenRouter).
    """
    _require_playground(request)
    s = request.app.state.settings
    return RouterMapResponse(
        dev=s.openrouter_model_dev,
        production=s.openrouter_model_production,
        demo=s.openrouter_model_demo,
    )


@router.post("/infer", response_model=InferResponse)
async def infer(request: Request, body: InferRequest) -> InferResponse:
    """
    Minimal chat completion through the tier router — for verifying OpenRouter connectivity.

    Not intended for production PHI workloads.
    """
    _require_playground(request)
    tier = ModelTier(body.tier)
    routed = _router_from_settings(request).resolve(tier)
    openrouter = getattr(request.app.state, "openrouter", None)
    if openrouter is None:
        raise HTTPException(
            status_code=500, detail="OpenRouter client not initialized."
        )

    messages: list[dict[str, str]] = []
    messages.append(
        {
            "role": "system",
            "content": body.system or "You are a concise, accurate assistant.",
        }
    )
    messages.append({"role": "user", "content": body.prompt})

    try:
        result = await openrouter.chat_completion(
            model=routed.model_id,
            messages=messages,
            temperature=0.2 if tier is not ModelTier.DEMO else 0.35,
            max_completion_tokens=256,
            langfuse_task_type=f"playground_infer_{body.tier}",
            langfuse_trace_name="llm-playground-infer",
            langfuse_metadata={
                "playground_tier": body.tier,
                "route": "POST /llm/infer",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"OpenRouter request failed: {exc}"
        ) from exc

    usage = dict(result.usage) if isinstance(result.usage, dict) else result.usage
    return InferResponse(
        reply=result.content,
        tier=tier.value,
        model_requested=routed.model_id,
        model_reported=result.model,
        usage=usage,
    )
