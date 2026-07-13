"""Text-to-speech providers.

Default provider is edge-tts (free, no API key). ElevenLabs is available for
higher quality when an API key is configured.

``synthesize`` returns word-level timings when the provider supports them
(edge-tts does), which powers the animated word-by-word captions.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path

from ..config import settings
from ..models import WordTiming

logger = logging.getLogger(__name__)

# Deep male voices that fit the dark cinematic tone. A random voice is picked
# per video so consecutive Shorts sound distinct on the feed.
_EDGE_VOICE_POOL = [
    "en-US-GuyNeural",       # deep, authoritative
    "en-US-DavisNeural",     # warm, slightly lower
    "en-GB-RyanNeural",      # British, dramatic
    "en-AU-WilliamNeural",   # Australian, distinct
    "en-US-AndrewNeural",    # calm, narrator-like
]
_EDGE_MAX_ATTEMPTS = 3
_EDGE_RETRY_BASE_SECONDS = 2


def synthesize(text: str, out_path: Path) -> list[WordTiming]:
    """Synthesize ``text`` to an mp3 at ``out_path``; return word timings."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    provider = settings.tts_provider
    if provider == "elevenlabs":
        return _elevenlabs(text, out_path)
    return _edge(text, out_path)


# Cached per-process so every scene in one video uses the same voice.
_session_voice: str | None = None


def pick_voice_for_video() -> str:
    """Choose and cache the voice for the current video run.

    Call once at the start of the pipeline. All scenes then use the same voice.
    """
    global _session_voice  # noqa: PLW0603
    voice = settings.edge_tts_voice
    if voice.lower() == "random":
        voice = random.choice(_EDGE_VOICE_POOL)
    _session_voice = voice
    logger.info("Voice for this video: %s", voice)
    return voice


def _edge(text: str, out_path: Path) -> list[WordTiming]:
    import edge_tts  # lazy import

    global _session_voice  # noqa: PLW0603
    voice = _session_voice or pick_voice_for_video()
    last_error: Exception | None = None

    for attempt in range(1, _EDGE_MAX_ATTEMPTS + 1):
        words: list[WordTiming] = []

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text, voice, rate=settings.tts_rate, boundary="WordBoundary"
            )
            with open(out_path, "wb") as fh:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        fh.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        start = chunk["offset"] / 1e7
                        end = start + chunk["duration"] / 1e7
                        words.append(
                            WordTiming(text=chunk["text"], start=start, end=end)
                        )

        try:
            if out_path.exists():
                out_path.unlink()
            asyncio.run(_run())
            if not out_path.exists() or out_path.stat().st_size == 0:
                raise RuntimeError("edge-tts produced no audio.")
            return words
        except Exception as exc:  # noqa: BLE001 - remote service is transient
            last_error = exc
            if out_path.exists():
                out_path.unlink()
            if attempt == _EDGE_MAX_ATTEMPTS:
                break
            delay = _EDGE_RETRY_BASE_SECONDS * attempt
            fallbacks = [v for v in _EDGE_VOICE_POOL if v != voice]
            if attempt >= 2 and fallbacks:
                voice = random.choice(fallbacks)
                _session_voice = voice  # keep later scenes on the same voice
            logger.warning(
                "Edge TTS failed (attempt %d/%d), retrying in %ds with voice %s: %s",
                attempt,
                _EDGE_MAX_ATTEMPTS,
                delay,
                voice,
                exc,
            )
            time.sleep(delay)

    raise RuntimeError(
        f"Edge TTS failed after {_EDGE_MAX_ATTEMPTS} attempts: {last_error}"
    ) from last_error


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
