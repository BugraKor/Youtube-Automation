"""Text-to-speech providers.

Default provider is edge-tts (free, no API key). ElevenLabs is available for
higher quality when an API key is configured.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)


def synthesize(text: str, out_path: Path) -> Path:
    """Synthesize ``text`` to an mp3 at ``out_path``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    provider = settings.tts_provider
    if provider == "elevenlabs":
        return _elevenlabs(text, out_path)
    return _edge(text, out_path)


def _edge(text: str, out_path: Path) -> Path:
    import edge_tts  # lazy import

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, settings.edge_tts_voice)
        await communicate.save(str(out_path))

    asyncio.run(_run())
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("edge-tts produced no audio.")
    return out_path


def _elevenlabs(text: str, out_path: Path) -> Path:
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
    return out_path
