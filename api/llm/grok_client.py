"""
Async OpenRouter client using the OpenAI-compatible Chat Completions HTTP API.

Endpoint: ``POST {base_url}/chat/completions`` (default base ``https://openrouter.ai/api/v1``).

Authentication: ``Authorization: Bearer <OPENROUTER_API_KEY>`` (or ``XAI_API_KEY`` legacy).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx

from api.observability.langfuse_client import get_langfuse, usage_to_langfuse
from api.settings import Settings


@dataclass(frozen=True)
class ChatCompletionResult:
    """Normalized chat completion response."""

    content: str
    model: str
    raw: Mapping[str, Any]
    usage: Mapping[str, Any] | None


class OpenRouterClient:
    """
    Thin wrapper over OpenRouter chat completions. Reuses one httpx AsyncClient per instance.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=15.0),
                headers={"Accept": "application/json"},
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _require_api_key(self) -> str:
        key = self._settings.resolved_openrouter_api_key
        if not key:
            raise ValueError(
                "OpenRouter API key is not set. Add OPENROUTER_API_KEY or XAI_API_KEY to the environment."
            )
        return key

    async def chat_completion(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, str]],
        temperature: float = 0.2,
        max_completion_tokens: int | None = 512,
        langfuse_task_type: str = "llm_call",
        langfuse_trace_name: str | None = None,
        langfuse_metadata: Mapping[str, Any] | None = None,
    ) -> ChatCompletionResult:
        """
        Call OpenRouter chat completions and return assistant text.

        ``messages`` items must include ``role`` and ``content`` keys (OpenAI shape).

        When Langfuse keys are configured (see Settings), each call is recorded as a
        generation with ``metadata.task_type`` set to ``langfuse_task_type`` for
        dashboards and cost attribution by task class (orchestrator, playground, etc.).
        """
        lf = get_langfuse(self._settings)
        trace_name = langfuse_trace_name or f"openrouter-{langfuse_task_type}"
        meta: dict[str, Any] = {
            "task_type": langfuse_task_type,
            "provider": "openrouter",
            "openrouter_api_base": self._settings.openrouter_api_base_url,
        }
        if langfuse_metadata:
            meta.update(dict(langfuse_metadata))

        model_params: dict[str, Any] = {"temperature": temperature}
        if max_completion_tokens is not None:
            model_params["max_completion_tokens"] = max_completion_tokens

        if lf is None:
            return await self._chat_completion_raw(
                model=model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
            )

        with lf.start_as_current_observation(
            name=trace_name,
            as_type="generation",
            model=model,
            input=list(messages),
            metadata=meta,
            model_parameters=model_params,
        ) as generation:
            try:
                result = await self._chat_completion_raw(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_completion_tokens=max_completion_tokens,
                )
            except Exception as exc:
                generation.update(
                    level="ERROR",
                    status_message=str(exc)[:2000],
                )
                raise

            ud = usage_to_langfuse(
                result.usage if isinstance(result.usage, Mapping) else None
            )
            generation.update(
                output=result.content,
                usage_details=ud or None,
            )
            return result

    async def _chat_completion_raw(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, str]],
        temperature: float = 0.2,
        max_completion_tokens: int | None = 512,
    ) -> ChatCompletionResult:
        """Perform HTTP call without Langfuse (also used inside traced path)."""
        api_key = self._require_api_key()
        base = self._settings.openrouter_api_base_url.rstrip("/")
        url = f"{base}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if max_completion_tokens is not None:
            payload["max_completion_tokens"] = max_completion_tokens
            payload["max_tokens"] = max_completion_tokens

        resp = await self._client().post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = resp.text
            raise RuntimeError(
                f"OpenRouter API request failed (status={resp.status_code}): {body}"
            ) from exc

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter response contained no choices")
        message = choices[0].get("message") or {}
        content = message.get("content")
        if content is None:
            raise RuntimeError("OpenRouter response missing assistant content")
        return ChatCompletionResult(
            content=str(content).strip(),
            model=str(data.get("model") or model),
            raw=data,
            usage=data.get("usage"),
        )
