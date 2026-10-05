"""
Short-lived blocking subscriber for ``healthos:agent:events``.

Run from the repository root (so ``import api`` works):

    python tests/redis_next_steps/listen_agent_events.py

In another terminal, publish (example):

    python -c "import asyncio; from redis.asyncio import Redis; from api.events.agent_events import publish_agent_event; asyncio.run(publish_agent_event(Redis.from_url('redis://localhost:6379/0', decode_responses=True), event_type='demo', data={'hello': 'world'}))"

Or run the pub/sub unittest, which publishes programmatically.

Press Ctrl+C to stop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Repo root on sys.path when executed as ``python tests/redis_next_steps/listen_agent_events.py``
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import os

import redis as redis_sync

from api.events.agent_events import CHANNEL_AGENT_EVENTS_ALL


def _redis_url() -> str:
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0").strip()


def main() -> None:
    client = redis_sync.Redis.from_url(_redis_url(), decode_responses=True)
    pubsub = client.pubsub()
    pubsub.subscribe(CHANNEL_AGENT_EVENTS_ALL)
    print(f"Listening on {CHANNEL_AGENT_EVENTS_ALL!r} — Ctrl+C to exit", flush=True)
    for message in pubsub.listen():
        if message["type"] != "message":
            continue
        raw = message["data"]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        print(json.dumps(payload, indent=2), flush=True)


if __name__ == "__main__":
    main()
