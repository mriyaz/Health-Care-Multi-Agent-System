"""Platform asyncio tweaks (Windows + psycopg LangGraph checkpoints)."""

from __future__ import annotations

import asyncio
import sys


def configure_windows_event_loop() -> None:
    """
    psycopg3 async pools (LangGraph ``AsyncPostgresSaver``) require SelectorEventLoop on Windows.

    Without this, checkpoint writes hang and orchestrator background tasks never commit, leaving
    tasks stuck in ``QUEUED`` while the SOAP review UI polls forever.
    """
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
