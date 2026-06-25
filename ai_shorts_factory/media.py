"""FFmpeg helpers: probing, Ken Burns clips, subtitles and final assembly."""

from __future__ import annotations

import json
import logging
import subprocess
import textwrap
from pathlib import Path

from .config import settings
from .models import Scene

logger = logging.getLogger(__name__)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    logger.debug("ffmpeg: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}"
        )


def probe_duration(path: Path) -> float:
    """Return media duration in seconds using ffprobe."""
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {proc.stderr}")
    data = json.loads(proc.stdout)
    return float(data["format"]["duration"])


def make_ken_burns_clip(image: Path, duration: float, out_path: Path, *, zoom_in: bool) -> Path:
    """Render a single image into a vertical clip with a slow zoom/pan."""
    w, h = settings.video_width, settings.video_height
    fps = settings.video_fps
    frames = max(1, round(duration * fps))
    sw, sh = int(w * 1.5), int(h * 1.5)  # upscale to keep the zoom smooth

    if zoom_in:
        zexpr = "min(zoom+0.0015,1.20)"
    else:
        zexpr = "if(eq(on,1),1.20,max(zoom-0.0015,1.0))"

    vf = (
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
        f"crop={sw}:{sh},"
        f"zoompan=z='{zexpr}':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={w}x{h}:fps={fps},setsar=1,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(image),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    _run(cmd)
    return out_path


def concat_videos(clips: list[Path], out_path: Path, workdir: Path) -> Path:
    list_file = workdir / "video_concat.txt"
    list_file.write_text(
        "".join(f"file '{c.resolve()}'\n" for c in clips), encoding="utf-8"
    )
    _run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(out_path),
        ]
    )
    return out_path


def concat_audio(tracks: list[Path], out_path: Path, workdir: Path) -> Path:
    list_file = workdir / "audio_concat.txt"
    list_file.write_text(
        "".join(f"file '{t.resolve()}'\n" for t in tracks), encoding="utf-8"
    )
    _run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c:a", "libmp3lame", "-q:a", "2",
            str(out_path),
        ]
    )
    return out_path


def _fmt_ts(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass(text: str) -> str:
    text = text.replace("\\", " ").replace("{", "(").replace("}", ")")
    wrapped = textwrap.fill(text, width=20)
    return wrapped.replace("\n", "\\N")


def build_subtitles(scenes: list[Scene], out_path: Path) -> Path:
    """Build a styled .ass subtitle file timed to each scene's narration."""
    w, h = settings.video_width, settings.video_height
    font_size = int(h * 0.045)
    margin_v = int(h * 0.22)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{max(3, font_size // 8)},2,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    t = 0.0
    for scene in scenes:
        start = t
        end = t + scene.duration
        text = _escape_ass(scene.narration)
        lines.append(
            f"Dialogue: 0,{_fmt_ts(start)},{_fmt_ts(end)},Default,,0,0,0,,{text}\n"
        )
        t = end
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def assemble(
    video_only: Path,
    voice: Path,
    subtitles: Path,
    out_path: Path,
    workdir: Path,
) -> Path:
    """Burn subtitles, mux voice (+optional background music) into final video."""
    music = settings.background_music
    inputs = ["-i", str(video_only.resolve()), "-i", str(voice.resolve())]
    use_music = bool(music) and Path(music).exists()

    if use_music:
        inputs = ["-stream_loop", "-1", "-i", str(Path(music).resolve())] + inputs
        # indexes: 0=music, 1=video, 2=voice
        filter_complex = (
            f"[1:v]subtitles={subtitles.name}[v];"
            f"[0:a]volume={settings.music_volume}[m];"
            f"[2:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]"
        )
    else:
        filter_complex = f"[0:v]subtitles={subtitles.name}[v];[1:a]anull[a]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path.resolve()),
    ]
    _run(cmd, cwd=workdir)
    return out_path
