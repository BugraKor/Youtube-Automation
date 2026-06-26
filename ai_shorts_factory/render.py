"""Assemble a finished vertical Short from prepared scenes."""

from __future__ import annotations

import logging
from pathlib import Path

from . import media
from .config import settings
from .models import VideoProject

logger = logging.getLogger(__name__)


def render_video(project: VideoProject) -> Path:
    """Turn a project whose scenes have images + audio + durations into an mp4."""
    if not project.workdir:
        raise ValueError("project.workdir must be set before rendering.")
    workdir = project.workdir
    clips_dir = workdir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    transition = settings.transition_duration

    clips: list[Path] = []
    audios: list[Path] = []
    durations: list[float] = []
    for scene in project.scenes:
        if not scene.image_path or not scene.audio_path:
            raise ValueError(f"Scene {scene.index} missing image or audio.")
        clip = clips_dir / f"scene_{scene.index:02d}.mp4"
        media.make_ken_burns_clip(
            scene.image_path,
            scene.duration,
            clip,
            zoom_in=(scene.index % 2 == 0),
        )
        clips.append(clip)
        audios.append(scene.audio_path)
        durations.append(scene.duration)
        logger.info("Rendered scene %d (%.2fs)", scene.index, scene.duration)

    video_only = media.concat_videos_xfade(
        clips, durations, workdir / "video_only.mp4", workdir, transition
    )
    voice = media.concat_audio_crossfade(
        audios, workdir / "voice.mp3", workdir, transition
    )
    subtitles = media.build_subtitles(
        project.scenes, workdir / "subtitles.ass", transition
    )

    starts, _ = media.scene_start_times(durations, transition)
    boundaries = starts[1:]  # one whoosh per scene transition

    final = workdir / "final.mp4"
    media.assemble(video_only, voice, subtitles, final, workdir, boundaries=boundaries)
    project.video_path = final
    logger.info("Final video: %s", final)
    return final
