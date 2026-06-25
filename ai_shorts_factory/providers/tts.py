"""Text-to-speech providers.

Default provider is edge-tts (free, no API key). ElevenLabs is available for
higher quality when an API key is configured.

``synthesize`` returns word-level timings when the provider supports them
(edge-tts does), which powers the animated word-by-word captions.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..config import settings
from ..models import WordTiming

logger = logging.getLogger(__name__)


def synthesize(text: str, out_path: Path) -> list[WordTiming]:
    """Synthesize ``text`` to an mp3 at ``out_path``; return word timings."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    provider = settings.tts_provider
    if provider == "elevenlabs":
        return _elevenlabs(text, out_path)
    return _edge(text, out_path)


def _edge(text: str, out_path: Path) -> list[WordTiming]:
    import edge_tts  # lazy import

    words: list[WordTiming] = []

    async def _run() -> None:
        communicate = edge_tts.Communicate(
            text, settings.edge_tts_voice, boundary="WordBoundary"
        )
        with open(out_path, "wb") as fh:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    fh.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    end = start + chunk["duration"] / 1e7
                    words.append(WordTiming(text=chunk["text"], start=start, end=end))

    asyncio.run(_run())
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("edge-tts produced no audio.")
    return words


def _elevenlabs(text: str, out_path: Path) -> list[WordTiming]:
    if not settings.elevenlabs_api_key:
        raise RuntimeError("TTS_PROVIDER=elevenlabs but ELEVENLABS_API_KEY is not set.")
    from elevenlabs.client import ElevenLabs  # lazy import

    client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    audio = client.text_to_speech.convert(
        voice_id=settings.elevenlabs_voice_id,
        model_id="eleven_multilingual_v2",
        text=text,
        output_format="mp3_44100_128",
    )
    with open(out_path, "wb") as fh:
        for chunk in audio:
            if chunk:
                fh.write(chunk)
    if out_path.stat().st_size == 0:
        raise RuntimeError("ElevenLabs produced no audio.")
    # Word timings not collected here; captions fall back to per-scene text.
    return []
