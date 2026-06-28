"""FFmpeg helpers: probing, Ken Burns clips, subtitles and final assembly."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
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


def open_in_player(path: Path) -> None:
    """Open a media file in the system default player.

    Used to preview a rendered Short locally without relying on an in-IDE video
    preview (some editors crash trying to render large videos inline).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Cannot preview, file does not exist: {path}")
    logger.info("Opening preview: %s", path)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: SC200 - Windows-only
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:  # noqa: BLE001 - preview is best-effort
        logger.warning("Could not open preview automatically (%s). Open it manually: %s", exc, path)


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


def trim_leading_silence(src: Path, out_path: Path, *, threshold_db: int = -35) -> Path:
    """Remove leading silence from an audio file.

    On Shorts, voice must start within ~0.3s of frame 0 — any silence at the
    beginning causes viewers to swipe. Uses silenceremove to cut dead air.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-y",
            "-i", str(src.resolve()),
            "-af",
            f"silenceremove=start_periods=1:start_duration=0.02:"
            f"start_threshold={threshold_db}dB",
            "-c:a", "libmp3lame", "-q:a", "2",
            str(out_path.resolve()),
        ]
    )
    return out_path


def make_stock_clip(
    video: Path, duration: float, out_path: Path,
) -> Path:
    """Trim and reformat a stock video clip to fit the scene duration.

    Crops to 9:16 if needed, applies the same cinematic grading as Ken Burns
    clips, and trims to exactly *duration* seconds.
    """
    w, h = settings.video_width, settings.video_height
    fps = settings.video_fps
    grain = "noise=alls=5:allf=t+u," if settings.film_grain else ""
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},"
        f"fps={fps},setsar=1,"
        f"eq=contrast=1.06:saturation=1.14:brightness=-0.015:gamma=0.98,"
        f"unsharp=5:5:0.4:5:5:0.0,"
        f"{grain}"
        f"vignette=PI/5.0,format=yuv420p"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", vf,
        "-t", f"{duration:.3f}",
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-an",
        str(out_path),
    ]
    _run(cmd)
    return out_path


def make_ken_burns_clip(
    image: Path, duration: float, out_path: Path, *, zoom_in: bool, is_hook: bool = False
) -> Path:
    """Render a single image into a vertical clip with a slow zoom/pan.

    When *is_hook* is True (scene 0), the zoom starts faster so the very first
    frame has visible movement — research shows static openings get swiped.
    """
    w, h = settings.video_width, settings.video_height
    fps = settings.video_fps
    frames = max(1, round(duration * fps))
    sw, sh = int(w * 1.5), int(h * 1.5)  # upscale to keep the zoom smooth

    # Faster initial zoom for the hook scene so frame 0 is never static.
    step = "0.0020" if is_hook else "0.0012"
    if zoom_in:
        zexpr = f"min(zoom+{step},1.18)"
    else:
        zexpr = f"if(eq(on,1),1.18,max(zoom-{step},1.0))"

    grain = "noise=alls=7:allf=t+u," if settings.film_grain else ""
    vf = (
        f"scale={sw}:{sh}:force_original_aspect_ratio=increase,"
        f"crop={sw}:{sh},"
        f"zoompan=z='{zexpr}':d={frames}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={w}x{h}:fps={fps},setsar=1,"
        f"eq=contrast=1.06:saturation=1.14:brightness=-0.015:gamma=0.98,"
        f"unsharp=5:5:0.6:5:5:0.0,"
        f"{grain}"
        f"vignette=PI/4.5,format=yuv420p"
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


def pad_audio_tail(src: Path, out_path: Path, seconds: float) -> Path:
    """Copy ``src`` adding ``seconds`` of trailing silence (keeps word timings)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg", "-y",
            "-i", str(src.resolve()),
            "-af", f"apad=pad_dur={seconds:.3f}",
            "-c:a", "libmp3lame", "-q:a", "2",
            str(out_path.resolve()),
        ]
    )
    return out_path


def scene_start_times(durations: list[float], transition: float) -> tuple[list[float], float]:
    """Return (per-scene start times, total duration) accounting for crossfades."""
    starts: list[float] = []
    acc = 0.0
    n = len(durations)
    for i, d in enumerate(durations):
        starts.append(acc)
        acc += d - (transition if i < n - 1 else 0.0)
    return starts, acc


def concat_videos_xfade(
    clips: list[Path], durations: list[float], out_path: Path, workdir: Path, transition: float
) -> Path:
    """Concatenate clips with smooth crossfades between them."""
    if transition <= 0 or len(clips) < 2:
        return concat_videos(clips, out_path, workdir)

    fps = settings.video_fps
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c.resolve())]

    parts: list[str] = []
    for i in range(len(clips)):
        parts.append(f"[{i}:v]settb=AVTB,fps={fps},format=yuv420p[v{i}]")

    prev = "v0"
    acc = durations[0]
    for i in range(1, len(clips)):
        offset = max(0.0, acc - transition)
        out_lbl = "vout" if i == len(clips) - 1 else f"x{i}"
        parts.append(
            f"[{prev}][v{i}]xfade=transition=fade:duration={transition:.3f}:"
            f"offset={offset:.3f}[{out_lbl}]"
        )
        prev = out_lbl
        acc += durations[i] - transition

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "[vout]",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
        "-pix_fmt", "yuv420p",
        str(out_path.resolve()),
    ]
    _run(cmd)
    return out_path


def concat_audio_crossfade(
    tracks: list[Path], out_path: Path, workdir: Path, transition: float
) -> Path:
    """Concatenate voice tracks with short crossfades so cuts are seamless."""
    if transition <= 0 or len(tracks) < 2:
        return concat_audio(tracks, out_path, workdir)

    inputs: list[str] = []
    for t in tracks:
        inputs += ["-i", str(t.resolve())]

    parts: list[str] = []
    for i in range(len(tracks)):
        parts.append(f"[{i}:a]aresample=44100[a{i}]")
    prev = "a0"
    for i in range(1, len(tracks)):
        out_lbl = "aout" if i == len(tracks) - 1 else f"ac{i}"
        parts.append(
            f"[{prev}][a{i}]acrossfade=d={transition:.3f}:c1=tri:c2=tri[{out_lbl}]"
        )
        prev = out_lbl

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "[aout]",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(out_path.resolve()),
    ]
    _run(cmd)
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


# Entrance pop applied to every caption phrase.
_POP = r"{\fad(60,35)\t(0,100,\fscx110\fscy110)\t(100,200,\fscx100\fscy100)}"


def build_subtitles(scenes: list[Scene], out_path: Path, transition: float = 0.0) -> Path:
    """Build a styled .ass subtitle file synced to the (crossfaded) timeline.

    When word timings are available, captions are rendered TikTok-style: short
    2-3 word phrases that pop in and light up word-by-word in sync with the
    voiceover. Otherwise it falls back to one caption per scene.
    """
    w, h = settings.video_width, settings.video_height
    font_size = int(h * 0.058)
    margin_v = int(h * 0.27)
    side_margin = int(w * 0.10)
    outline = max(5, font_size // 6)
    shadow = max(2, font_size // 18)
    # Colours: ASS uses &HAABBGGRR. Active word = vivid yellow, unsung = bright
    # white. A high-contrast highlight increases retention by keeping eyes glued
    # to the word-by-word reveal (TikTok/Hormozi-style best practice). For cyan
    # instead, use &H00FFFF00.
    primary_colour = "&H0000FFFF"  # vivid yellow (active karaoke word)
    secondary_colour = "&H00FFFFFF"  # white (static/unsung text)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,{font_size},{primary_colour},{secondary_colour},&H00101010,&HB4000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,{side_margin},{side_margin},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    durations = [s.duration for s in scenes]
    starts, total = scene_start_times(durations, transition)
    lines = [header]
    for i, scene in enumerate(scenes):
        scene_start = starts[i]
        scene_end = starts[i + 1] if i + 1 < len(scenes) else total
        if scene.words:
            lines.extend(_word_dialogues(scene, scene_start, scene_end))
        else:
            text = _POP + "{\\c&H00FFFFFF&}" + _escape_ass(scene.narration)
            lines.append(
                f"Dialogue: 0,{_fmt_ts(scene_start)},{_fmt_ts(scene_end)},Default,,0,0,0,,{text}\n"
            )
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
        text = _POP + "".join(parts).rstrip()
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
    *,
    boundaries: list[float] | None = None,
) -> Path:
    """Burn subtitles and build the final mix.

    Audio chain: voice is loudness-normalised and lightly compressed for a
    consistent, present sound; an ambient music bed is mixed in and ducked under
    the voice (sidechain); short whoosh SFX hit each scene transition.
    """
    boundaries = boundaries or []
    total = probe_duration(video_only)
    fade_out_start = max(0.0, total - 0.5)

    music = settings.background_music
    use_music = bool(music) and Path(music).exists()
    sfx = settings.sfx_file
    use_sfx = settings.enable_sfx and bool(sfx) and Path(sfx).exists() and bool(boundaries)
    impact = settings.sfx_impact_file
    use_impact = settings.enable_sfx and bool(impact) and Path(impact).exists()

    # ---- inputs ----
    inputs: list[str] = ["-i", str(video_only.resolve()), "-i", str(voice.resolve())]
    video_idx, voice_idx = 0, 1
    next_idx = 2
    music_idx = sfx_idx = impact_idx = None
    if use_music:
        inputs += ["-stream_loop", "-1", "-i", str(Path(music).resolve())]
        music_idx = next_idx
        next_idx += 1
    if use_sfx:
        inputs += ["-i", str(Path(sfx).resolve())]
        sfx_idx = next_idx
        next_idx += 1
    if use_impact:
        inputs += ["-i", str(Path(impact).resolve())]
        impact_idx = next_idx
        next_idx += 1

    parts: list[str] = []
    # Keep the opening fade-in tiny so frame 0 (the hook) is visible instantly:
    # on Shorts the first moment decides "viewed vs swiped away".
    parts.append(
        f"[{video_idx}:v]subtitles={subtitles.name},"
        f"fade=t=in:st=0:d=0.12,fade=t=out:st={fade_out_start:.3f}:d=0.5,"
        f"format=yuv420p[v]"
    )

    vox_chain = (
        f"[{voice_idx}:a]loudnorm=I=-15:TP=-1.5:LRA=11,"
        "acompressor=threshold=-18dB:ratio=3:attack=8:release=180,apad"
    )
    mix_labels: list[str] = []
    if use_music:
        parts.append(f"{vox_chain},asplit=2[vox][voxkey]")
        parts.append(
            f"[{music_idx}:a]volume={settings.music_volume},afade=t=in:st=0:d=1.5[mv]"
        )
        parts.append(
            "[mv][voxkey]sidechaincompress=threshold=0.05:ratio=6:attack=5:release=350[mduck]"
        )
        mix_labels += ["[vox]", "[mduck]"]
    else:
        parts.append(f"{vox_chain}[vox]")
        mix_labels.append("[vox]")

    if use_sfx:
        k = len(boundaries)
        split_labels = "".join(f"[sfa{i}]" for i in range(k))
        parts.append(f"[{sfx_idx}:a]volume={settings.sfx_volume},asplit={k}{split_labels}")
        for i, tb in enumerate(boundaries):
            ms = max(0, int((tb - 0.12) * 1000))
            parts.append(f"[sfa{i}]adelay={ms}|{ms}[sfx{i}]")
            mix_labels.append(f"[sfx{i}]")

    # Opening impact hit at t=0 — grabs attention in the first frame.
    if use_impact:
        parts.append(
            f"[{impact_idx}:a]volume={settings.sfx_impact_volume}[imp]"
        )
        mix_labels.append("[imp]")

    if len(mix_labels) == 1:
        audio_out = mix_labels[0]
    else:
        parts.append(
            "".join(mix_labels)
            + f"amix=inputs={len(mix_labels)}:normalize=0:dropout_transition=0,"
            "alimiter=limit=0.95[a]"
        )
        audio_out = "[a]"

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", ";".join(parts),
        "-map", "[v]", "-map", audio_out,
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-t", f"{total:.3f}",
        str(out_path.resolve()),
    ]
    _run(cmd, cwd=workdir)
    return out_path
