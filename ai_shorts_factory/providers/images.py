"""Image generation providers.

Default provider is Gemini (Imagen 4 — requires billing on AI Studio).
Fallback is Pollinations (free, no API key, uses Flux model with enhanced
prompts and aggressive post-processing for maximum quality).
"""

from __future__ import annotations

import io
import logging
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from ..config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 120

# Appended to every prompt for a consistent, premium cinematic look.
# More specific visual anchors = better quality from generative models.
_STYLE_SUFFIX = (
    "cinematic film still, shot on ARRI Alexa Mini LF with Cooke Anamorphic/i "
    "SF 50mm T1.4 lens, shallow depth of field with creamy bokeh, dramatic "
    "volumetric god-rays, rich teal-and-orange color grading, "
    "ultra detailed textures, photorealistic CGI quality, 8K resolution, "
    "high dynamic range, subtle film grain, atmospheric particles and haze, "
    "epic cinematic mood, vertical 9:16 aspect ratio composition, "
    "no text, no watermark, no UI elements, masterpiece quality"
)


def _styled(prompt: str) -> str:
    return f"{prompt.rstrip(' .,')}, {_STYLE_SUFFIX}"


def generate_image(prompt: str, out_path: Path, *, seed: int | None = None) -> Path:
    """Generate one image for ``prompt`` and save it to ``out_path``.

    If the configured provider fails (e.g. Gemini without billing), falls back
    to Pollinations automatically so the pipeline never stalls.
    """
    provider = settings.image_provider
    if provider == "gemini":
        try:
            return _gemini_image(_styled(prompt), out_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Gemini image generation failed (%s); falling back to Pollinations.", exc
            )
    return _pollinations_image(_styled(prompt), out_path, seed=seed)


def _save_normalized(data: bytes, out_path: Path) -> Path:
    """Decode bytes, apply cinema-grade post-processing, save at target res."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    target = (settings.video_width, settings.video_height)
    if img.size != target:
        img = _cover_resize(img, target)
    if settings.image_enhance:
        # Multi-pass sharpening: detail pass (small radius) + clarity pass (large)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=80, threshold=1))
        img = img.filter(ImageFilter.UnsharpMask(radius=4.0, percent=40, threshold=2))
        # Cinematic contrast + saturation boost
        img = ImageEnhance.Contrast(img).enhance(1.12)
        img = ImageEnhance.Color(img).enhance(1.15)
        # Slight brightness reduction for that dark cinematic look
        img = ImageEnhance.Brightness(img).enhance(0.92)
        # Auto-level histogram for better tonal range
        img = ImageOps.autocontrast(img, cutoff=0.3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG", optimize=True)
    return out_path


def _cover_resize(img: Image.Image, target: tuple[int, int]) -> Image.Image:
    """Resize+center-crop so the image fully covers ``target`` (no bars)."""
    tw, th = target
    scale = max(tw / img.width, th / img.height)
    nw, nh = round(img.width * scale), round(img.height * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def _pollinations_image(prompt: str, out_path: Path, *, seed: int | None = None) -> Path:
    encoded = urllib.parse.quote(prompt)
    params = {
        "width": settings.video_width,
        "height": settings.video_height,
        "nologo": "true",
        "nofeed": "true",
        "model": "flux",
        "enhance": "true",
    }
    if seed is not None:
        params["seed"] = seed
    url = f"https://image.pollinations.ai/prompt/{encoded}?" + urllib.parse.urlencode(
        params
    )

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            if not resp.content:
                raise ValueError("empty image response")
            return _save_normalized(resp.content, out_path)
        except Exception as exc:  # noqa: BLE001 - retry on any network error
            last_err = exc
            logger.warning("Pollinations attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Pollinations image generation failed: {last_err}")


def _gemini_image(prompt: str, out_path: Path) -> Path:
    settings.validate_text()
    from google import genai  # lazy import

    client = genai.Client(api_key=settings.gemini_api_key)
    result = client.models.generate_images(
        model=settings.gemini_image_model,
        prompt=prompt,
        config={"number_of_images": 1, "aspect_ratio": "9:16"},
    )
    images = getattr(result, "generated_images", None) or []
    if not images:
        raise RuntimeError("Gemini returned no images.")
    image_bytes = images[0].image.image_bytes
    return _save_normalized(image_bytes, out_path)
