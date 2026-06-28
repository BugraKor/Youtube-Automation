"""Stock video provider — Pexels Video API (free, requires API key).

When a PEXELS_API_KEY is set, scenes can use real stock footage clips instead of
static images with Ken Burns zoom.  The pipeline queries Pexels for short
vertical clips that match each scene's image_prompt, downloads the best match,
and trims it to exactly the scene duration.

If no key is set or no suitable clip is found, returns ``None`` so the caller
can fall back to image-based rendering.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import requests

from ..config import settings

logger = logging.getLogger(__name__)

_PEXELS_SEARCH = "https://api.pexels.com/v1/videos/search"
_TIMEOUT = 30


def _api_key() -> str:
    return settings.pexels_api_key


def _extract_keywords(prompt: str, max_words: int = 4) -> str:
    """Distil a verbose image_prompt into a short Pexels search query."""
    stop = {
        "a", "an", "the", "of", "in", "on", "at", "for", "and", "or", "with",
        "is", "are", "was", "were", "from", "by", "to", "no", "its", "this",
        "that", "very", "extremely", "ultra", "style", "still", "cinematic",
        "photorealistic", "dramatic", "vertical", "composition", "detailed",
        "shot", "lens", "camera", "angle", "lighting", "light", "color",
        "colour", "mood", "haze", "particles", "fog", "dust", "embers",
        "volumetric", "depth", "field", "bokeh", "resolution", "quality",
        "masterpiece", "grade", "grading", "ray", "rays", "film", "grain",
        "watermark", "text", "aspect", "ratio", "elements", "ui",
    }
    words = re.findall(r"[a-zA-Z]+", prompt.lower())
    keywords = [w for w in words if w not in stop and len(w) > 2]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
        if len(unique) >= max_words:
            break
    return " ".join(unique) if unique else "cinematic dark"


def search_clip(
    prompt: str,
    out_path: Path,
    *,
    min_duration: float = 3.0,
    orientation: str = "portrait",
) -> Path | None:
    """Search Pexels for a clip matching *prompt* and download it.

    Returns the downloaded file path, or ``None`` if unavailable.
    """
    key = _api_key()
    if not key:
        return None

    query = _extract_keywords(prompt)
    params = {
        "query": query,
        "orientation": orientation,
        "per_page": 15,
        "size": "medium",
    }
    headers = {"Authorization": key}

    try:
        resp = requests.get(
            _PEXELS_SEARCH,
            params=params,
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pexels search failed for '%s': %s", query, exc)
        return None

    videos = data.get("videos", [])
    if not videos:
        logger.info("Pexels returned 0 results for '%s'", query)
        return None

    # Pick the best vertical clip that's long enough.
    best_file: dict | None = None
    for vid in videos:
        if vid.get("duration", 0) < min_duration:
            continue
        files = vid.get("video_files", [])
        # Prefer HD vertical files
        for vf in sorted(files, key=lambda f: f.get("height", 0), reverse=True):
            h = vf.get("height", 0)
            w = vf.get("width", 0)
            if h >= 720 and h > w:  # portrait
                best_file = vf
                break
        if best_file:
            break

    if not best_file:
        # Fallback: any file from the first video
        if videos and videos[0].get("video_files"):
            best_file = videos[0]["video_files"][0]

    if not best_file:
        logger.info("No suitable Pexels clip for '%s'", query)
        return None

    dl_url = best_file.get("link", "")
    if not dl_url:
        return None

    try:
        dl = requests.get(dl_url, timeout=120, stream=True)
        dl.raise_for_status()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "wb") as fh:
            for chunk in dl.iter_content(chunk_size=1024 * 256):
                fh.write(chunk)
        logger.info("Downloaded Pexels clip: %s (%s)", out_path.name, query)
        return out_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pexels download failed: %s", exc)
        return None
