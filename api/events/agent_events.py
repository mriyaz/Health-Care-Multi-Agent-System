"""
Publish agent lifecycle events on Redis pub/sub.

Subscribers can be SSE/Webhook workers or separate asyncio tasks. This module only defines
channel naming + JSON envelopes so orchestration code stays consistent.

Example:

    await publish_agent_event(redis, event_type="task.started", data={"task_id": "..."})
"""

from __future__ import annotations

import json
from typing import Any

# Broadcast channel for cross-tenant dev/diagnostics; tenant-scoped channels for production isolation.
CHANNEL_AGENT_EVENTS_ALL = "healthos:agent:events"


def channel_for_tenant(tenant_id: str) -> str:
    return f"healthos:agent:events:{tenant_id}"


async def publish_agent_event(
    redis,
    *,
    event_type: str,
    data: dict[str, Any],
    tenant_id: str | None = None,
) -> int:
    """
    Publish a JSON envelope; returns subscriber count from Redis.

    When ``tenant_id`` is set, the message is duplicated to both the global channel and the
    tenant-specific channel so a hospital can subscribe narrowly without missing shared tooling.
    """
    envelope = {
        "event_type": event_type,
        "tenant_id": tenant_id,
        "data": data,
    }
    raw = json.dumps(envelope, separators=(",", ":"))
    receivers = await redis.publish(CHANNEL_AGENT_EVENTS_ALL, raw)
    if tenant_id:
        receivers += await redis.publish(channel_for_tenant(tenant_id), raw)
    return int(receivers)
