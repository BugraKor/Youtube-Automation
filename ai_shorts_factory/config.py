"""Central configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT_DIR / "output"
ASSETS_DIR = ROOT_DIR / "assets"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None and value != "" else default
    except ValueError:
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value is not None and value != "" else default
    except ValueError:
        return default


@dataclass
class Settings:
    """Runtime settings for the whole pipeline."""

    # Text generation
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_text_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
    )

    # Image generation
    image_provider: str = field(
        default_factory=lambda: os.getenv("IMAGE_PROVIDER", "pollinations").lower()
    )
    gemini_image_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_IMAGE_MODEL", "imagen-3.0-generate-002")
    )

    # TTS
    tts_provider: str = field(
        default_factory=lambda: os.getenv("TTS_PROVIDER", "edge").lower()
    )
    edge_tts_voice: str = field(
        default_factory=lambda: os.getenv("EDGE_TTS_VOICE", "en-US-GuyNeural")
    )
    elevenlabs_api_key: str = field(
        default_factory=lambda: os.getenv("ELEVENLABS_API_KEY", "")
    )
    elevenlabs_voice_id: str = field(
        default_factory=lambda: os.getenv("ELEVENLABS_VOICE_ID", "JBFqnCBsd6RMkjVDRZzb")
    )

    # Content
    content_theme: str = field(
        default_factory=lambda: os.getenv("CONTENT_THEME", "mixed-curiosity")
    )
    content_language: str = field(
        default_factory=lambda: os.getenv("CONTENT_LANGUAGE", "en")
    )
    scenes_per_video: int = field(
        default_factory=lambda: _int(os.getenv("SCENES_PER_VIDEO"), 6)
    )

    # Video
    video_width: int = field(default_factory=lambda: _int(os.getenv("VIDEO_WIDTH"), 1080))
    video_height: int = field(
        default_factory=lambda: _int(os.getenv("VIDEO_HEIGHT"), 1920)
    )
    video_fps: int = field(default_factory=lambda: _int(os.getenv("VIDEO_FPS"), 30))
    background_music: str = field(
        default_factory=lambda: os.getenv(
            "BACKGROUND_MUSIC", str(ASSETS_DIR / "music" / "ambient_drone.mp3")
        )
    )
    music_volume: float = field(
        default_factory=lambda: _float(os.getenv("MUSIC_VOLUME"), 0.16)
    )

    # Quality / production polish
    transition_duration: float = field(
        default_factory=lambda: _float(os.getenv("TRANSITION_DURATION"), 0.35)
    )
    image_enhance: bool = field(
        default_factory=lambda: _bool(os.getenv("IMAGE_ENHANCE"), True)
    )
    film_grain: bool = field(
        default_factory=lambda: _bool(os.getenv("FILM_GRAIN"), True)
    )
    enable_sfx: bool = field(
        default_factory=lambda: _bool(os.getenv("ENABLE_SFX"), True)
    )
    sfx_file: str = field(
        default_factory=lambda: os.getenv(
            "SFX_WHOOSH_FILE", str(ASSETS_DIR / "sfx" / "whoosh.mp3")
        )
    )
    sfx_volume: float = field(
        default_factory=lambda: _float(os.getenv("SFX_VOLUME"), 0.35)
    )

    # YouTube
    youtube_client_secret_file: str = field(
        default_factory=lambda: os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
    )
    youtube_token_file: str = field(
        default_factory=lambda: os.getenv("YOUTUBE_TOKEN_FILE", "token.json")
    )
    youtube_refresh_token: str = field(
        default_factory=lambda: os.getenv("YOUTUBE_REFRESH_TOKEN", "")
    )
    youtube_privacy_status: str = field(
        default_factory=lambda: os.getenv("YOUTUBE_PRIVACY_STATUS", "public")
    )
    youtube_category_id: str = field(
        default_factory=lambda: os.getenv("YOUTUBE_CATEGORY_ID", "27")
    )
    youtube_made_for_kids: bool = field(
        default_factory=lambda: _bool(os.getenv("YOUTUBE_MADE_FOR_KIDS"), False)
    )

    def validate_text(self) -> None:
        if not self.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file "
                "(get one at https://aistudio.google.com/apikey)."
            )


settings = Settings()
