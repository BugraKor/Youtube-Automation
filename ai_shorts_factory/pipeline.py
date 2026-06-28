"""End-to-end orchestration: idea -> script -> assets -> rendered Short."""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from . import content, render
from .config import OUTPUT_DIR, settings
from .models import VideoProject
from .providers import images, tts
from .providers.videos import search_clip
from .media import pad_audio_tail, probe_duration, trim_leading_silence

# Snappier pacing: 0.35s pause keeps energy high without sounding rushed.
_TAIL_SECONDS = 0.35

logger = logging.getLogger(__name__)

HISTORY_FILE = OUTPUT_DIR / "history.json"


def _load_recent_topics(limit: int = 50) -> list[str]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return [entry["topic"] for entry in data][-limit:]
    except (json.JSONDecodeError, KeyError):
        return []


def _record_topic(topic: str, video_path: Path) -> None:
    data = []
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = []
    data.append(
        {
            "topic": topic,
            "video": str(video_path),
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def create_short(topic: str | None = None) -> VideoProject:
    """Run the full pipeline and return the completed project."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not topic:
        topic = content.generate_topic(avoid=_load_recent_topics())
    logger.info("Topic: %s", topic)

    slug = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = OUTPUT_DIR / slug
    (workdir / "images").mkdir(parents=True, exist_ok=True)
    (workdir / "audio").mkdir(parents=True, exist_ok=True)

    project = VideoProject(topic=topic, workdir=workdir)
    project.scenes = content.generate_script(topic)
    logger.info("Script: %d scenes", len(project.scenes))

    use_video = settings.use_stock_video and bool(settings.pexels_api_key)

    for scene in project.scenes:
        # Try stock video first, fall back to generated image.
        if use_video:
            clip_path = workdir / "clips_raw" / f"scene_{scene.index:02d}.mp4"
            clip = search_clip(scene.image_prompt, clip_path)
            if clip:
                scene.video_clip_path = clip
                logger.info("Scene %d: using stock video clip", scene.index)

        if not scene.video_clip_path:
            img = workdir / "images" / f"scene_{scene.index:02d}.png"
            images.generate_image(scene.image_prompt, img, seed=1000 + scene.index)
            scene.image_path = img

        raw = workdir / "audio" / f"scene_{scene.index:02d}_raw.mp3"
        scene.words = tts.synthesize(scene.narration, raw)

        # Trim leading silence on the hook scene so voice starts at frame 0.
        trimmed = raw
        if scene.index == 0:
            trimmed = workdir / "audio" / f"scene_{scene.index:02d}_trimmed.mp3"
            trim_leading_silence(raw, trimmed)

        # Pad a trailing pause into the audio itself so audio and video share an
        # identical timeline (keeps captions/voice perfectly in sync after
        # crossfades).
        aud = workdir / "audio" / f"scene_{scene.index:02d}.mp3"
        pad_audio_tail(trimmed, aud, _TAIL_SECONDS)
        scene.audio_path = aud
        scene.duration = max(1.2, probe_duration(aud))
        logger.info("Scene %d assets ready (%.2fs)", scene.index, scene.duration)

    render.render_video(project)
    project.metadata = content.generate_metadata(topic, project.full_narration)

    meta_path = workdir / "metadata.json"
    meta_path.write_text(
        json.dumps(
            {
                "topic": topic,
                "title": project.metadata.title,
                "description": project.metadata.description,
                "tags": project.metadata.tags,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _record_topic(topic, project.video_path)
    logger.info("Done: %s", project.video_path)
    return project
