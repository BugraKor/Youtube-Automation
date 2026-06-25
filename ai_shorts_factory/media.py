"""FFmpeg helpers: probing, Ken Burns clips, subtitles and final assembly."""

from __future__ import annotations

import json
import logging
import subprocess
import textwrap
from pathlib import Path

from .config import settings
from .models import Scene, WordTiming

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
        f"s={w}x{h}:fps={fps},setsar=1,"
        f"eq=contrast=1.07:saturation=1.12:brightness=-0.02,"
        f"vignette=PI/5,format=yuv420p"
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
    wrapped = textwrap.fill(text, width=18)
    return wrapped.replace("\n", "\\N")


def _escape_word(word: str) -> str:
    return word.replace("\\", "").replace("{", "(").replace("}", ")").strip()


def _chunk_words(words: list[WordTiming], max_words: int, max_chars: int):
    """Group consecutive words into short on-screen phrases."""
    chunk: list[WordTiming] = []
    length = 0
    for w in words:
        wlen = len(w.text) + 1
        if chunk and (len(chunk) >= max_words or length + wlen > max_chars):
            yield chunk
            chunk, length = [], 0
        chunk.append(w)
        length += wlen
    if chunk:
        yield chunk


def build_subtitles(scenes: list[Scene], out_path: Path) -> Path:
    """Build a styled .ass subtitle file.

    When word timings are available, captions are rendered TikTok-style: short
    2-3 word phrases that light up word-by-word in sync with the voiceover.
    Otherwise it falls back to one caption per scene.
    """
    w, h = settings.video_width, settings.video_height
    font_size = int(h * 0.055)
    margin_v = int(h * 0.30)
    outline = max(4, font_size // 7)
    # Colours are ASS &HAABBGGRR.  sung=yellow, unsung=white.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H0000FFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,{outline},3,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    t = 0.0
    for scene in scenes:
        scene_start = t
        scene_end = t + scene.duration
        if scene.words:
            lines.extend(_word_dialogues(scene, scene_start, scene_end))
        else:
            text = "{\\c&H00FFFFFF&}" + _escape_ass(scene.narration)
            lines.append(
                f"Dialogue: 0,{_fmt_ts(scene_start)},{_fmt_ts(scene_end)},Default,,0,0,0,,{text}\n"
            )
        t = scene_end
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def _word_dialogues(scene: Scene, scene_start: float, scene_end: float) -> list[str]:
    """Build karaoke (\\k) dialogue lines for one scene's word timings."""
    chunks = list(_chunk_words(scene.words, max_words=3, max_chars=18))
    out: list[str] = []
    for i, chunk in enumerate(chunks):
        start = scene_start + chunk[0].start
        # Hold the phrase until the next one begins (no flicker between phrases).
        if i + 1 < len(chunks):
            end = scene_start + chunks[i + 1][0].start
        else:
            end = scene_end
        parts = []
        for j, word in enumerate(chunk):
            nxt = chunk[j + 1].start if j + 1 < len(chunk) else word.end
            k_cs = max(1, int(round((nxt - word.start) * 100)))
            parts.append(f"{{\\k{k_cs}}}{_escape_word(word.text)} ")
        text = "".join(parts).rstrip()
        out.append(
            f"Dialogue: 0,{_fmt_ts(start)},{_fmt_ts(end)},Default,,0,0,0,,{text}\n"
        )
    return out


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
