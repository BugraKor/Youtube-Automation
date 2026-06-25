"""End-to-end orchestration: idea -> script -> assets -> rendered Short."""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

from . import content, render
from .config import OUTPUT_DIR
from .models import VideoProject
from .providers import images, tts
from .media import probe_duration

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

    for scene in project.scenes:
        img = workdir / "images" / f"scene_{scene.index:02d}.png"
        images.generate_image(scene.image_prompt, img, seed=1000 + scene.index)
        scene.image_path = img

        aud = workdir / "audio" / f"scene_{scene.index:02d}.mp3"
        scene.words = tts.synthesize(scene.narration, aud)
        scene.audio_path = aud
        scene.duration = max(1.2, probe_duration(aud) + 0.35)  # small tail pause
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
