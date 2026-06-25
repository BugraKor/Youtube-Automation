"""Shared data models for the pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Scene:
    """A single scene of a Short: one image, one narration line."""

    index: int
    narration: str
    image_prompt: str
    on_screen_text: str = ""
    image_path: Path | None = None
    audio_path: Path | None = None
    duration: float = 0.0


@dataclass
class VideoMetadata:
    title: str
    description: str
    tags: list[str] = field(default_factory=list)


@dataclass
class VideoProject:
    """Everything needed to assemble and upload one Short."""

    topic: str
    scenes: list[Scene] = field(default_factory=list)
    metadata: VideoMetadata | None = None
    workdir: Path | None = None
    video_path: Path | None = None

    @property
    def full_narration(self) -> str:
        return " ".join(s.narration for s in self.scenes)
