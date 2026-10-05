"""
Local Whisper transcription (Section D #39).

Uses the optional ``openai-whisper`` package when installed; otherwise callers must supply text.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def whisper_available() -> bool:
    try:
        import whisper  # noqa: F401

        return True
    except ImportError:
        return False


def transcribe_audio_file(
    audio_path: str | Path,
    *,
    model_name: str = "base",
    language: str | None = None,
) -> dict[str, Any]:
    """
    Run Whisper on an audio file on disk.

    Returns dict:
      - ``text``: full transcript
      - ``segments``: list of {id, start, end, text} when supported
      - ``language``: detected or forced language code
    """
    path = Path(audio_path)
    if not path.is_file():
        raise FileNotFoundError(str(path))

    import whisper

    model = whisper.load_model(model_name)
    kwargs: dict[str, Any] = {}
    if language:
        kwargs["language"] = language

    result = model.transcribe(str(path), **kwargs)
    segments_out: list[dict[str, Any]] = []
    for seg in result.get("segments") or []:
        segments_out.append(
            {
                "id": seg.get("id"),
                "start": seg.get("start"),
                "end": seg.get("end"),
                "text": (seg.get("text") or "").strip(),
            }
        )

    text = (result.get("text") or "").strip()
    # Light medical vocabulary post-processing (#39).
    for old, new in ((" hx ", " history "), (" Hx ", " History ")):
        if old in text:
            text = text.replace(old, new)
    return {
        "text": text,
        "segments": segments_out,
        "language": result.get("language"),
    }


def should_skip_whisper() -> bool:
    return os.environ.get("HEALTHOS_SKIP_WHISPER", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
