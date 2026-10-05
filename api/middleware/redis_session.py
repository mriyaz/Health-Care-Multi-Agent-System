"""
Redis-backed HTTP sessions: signed cookie holds an opaque session id; JSON payload in Redis.

Starlette ships cookie-only SessionMiddleware; this middleware keeps the same scope["session"]
dict contract so FastAPI Request.session behaves like the built-in middleware.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import itsdangerous
from fastapi import FastAPI
from itsdangerous.exc import BadSignature
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.settings import Settings

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisSessionMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        fastapi_app: FastAPI,
        *,
        key_prefix: str = "healthos:sess:",
    ) -> None:
        self.app = app
        self.fastapi_app = fastapi_app
        self.key_prefix = key_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        settings: Settings = self.fastapi_app.state.settings
        redis: Redis = self.fastapi_app.state.redis
        signer = itsdangerous.TimestampSigner(str(settings.session_secret_key))

        connection = HTTPConnection(scope)

        cookie_val = connection.cookies.get(settings.session_cookie_name)

        resolved_id: str | None = None
        if cookie_val:
            try:
                resolved_id = signer.unsign(
                    cookie_val.encode("utf-8"),
                    max_age=settings.session_max_age_seconds,
                ).decode("utf-8")
            except BadSignature:
                resolved_id = None

        raw_payload: str | None = None
        if resolved_id:
            raw_payload = await redis.get(f"{self.key_prefix}{resolved_id}")

        scope["session"] = json.loads(raw_payload) if raw_payload else {}

        had_redis_payload = raw_payload is not None
        persisted_id = resolved_id

        async def send_wrapper(message: Message) -> None:
            nonlocal persisted_id
            if message["type"] != "http.response.start":
                await send(message)
                return

            data = scope["session"]
            if data:
                if not persisted_id:
                    persisted_id = str(uuid.uuid4())
                await redis.set(
                    f"{self.key_prefix}{persisted_id}",
                    json.dumps(data, separators=(",", ":")),
                    ex=settings.session_max_age_seconds,
                )
                token = signer.sign(persisted_id.encode("utf-8")).decode("utf-8")
                headers = MutableHeaders(scope=message)
                headers.append(
                    "Set-Cookie",
                    _set_cookie(
                        settings=settings,
                        name=settings.session_cookie_name,
                        value=token,
                    ),
                )
            elif persisted_id is not None or had_redis_payload:
                if persisted_id is not None:
                    await redis.delete(f"{self.key_prefix}{persisted_id}")
                headers = MutableHeaders(scope=message)
                headers.append(
                    "Set-Cookie",
                    _clear_cookie(settings=settings, name=settings.session_cookie_name),
                )

            await send(message)

        await self.app(scope, receive, send_wrapper)


def _cookie_flags(settings: Settings) -> str:
    parts = [
        "httponly",
        f"path={settings.session_cookie_path}",
        f"samesite={settings.session_cookie_same_site}",
    ]
    if settings.session_cookie_secure:
        parts.append("secure")
    if settings.session_cookie_domain:
        parts.append(f"domain={settings.session_cookie_domain}")
    return "; ".join(parts)


def _set_cookie(*, settings: Settings, name: str, value: str) -> str:
    ma = settings.session_max_age_seconds
    max_age_part = f"Max-Age={ma}; " if ma else ""
    return f"{name}={value}; {max_age_part}{_cookie_flags(settings)}"


def _clear_cookie(*, settings: Settings, name: str) -> str:
    p = settings.session_cookie_path
    return (
        f"{name}=; Max-Age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; "
        f"path={p}; {_cookie_flags(settings)}"
    )
