"""Image generation providers.

Default provider is Pollinations (free, no API key). A Gemini/Imagen provider
is available when an API key is configured.
"""

from __future__ import annotations

import io
import logging
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageFilter

from ..config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 120

# Appended to every prompt for a consistent, premium cinematic look.
_STYLE_SUFFIX = (
    "cinematic still, shot on ARRI Alexa, 35mm anamorphic lens, shallow depth of "
    "field, dramatic volumetric lighting, rich teal-and-orange color grade, "
    "ultra detailed, photorealistic, 8k, high dynamic range, film grain, "
    "atmospheric haze, epic mood, vertical 9:16 composition, no text, no watermark"
)


def _styled(prompt: str) -> str:
    return f"{prompt.rstrip(' .,')}, {_STYLE_SUFFIX}"


def generate_image(prompt: str, out_path: Path, *, seed: int | None = None) -> Path:
    """Generate one image for ``prompt`` and save it to ``out_path``."""
    provider = settings.image_provider
    if provider == "gemini":
        return _gemini_image(_styled(prompt), out_path)
    return _pollinations_image(_styled(prompt), out_path, seed=seed)


def _save_normalized(data: bytes, out_path: Path) -> Path:
    """Decode bytes, polish, and re-save at the exact target resolution."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    target = (settings.video_width, settings.video_height)
    if img.size != target:
        img = _cover_resize(img, target)
    if settings.image_enhance:
        img = img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=110, threshold=2))
        img = ImageEnhance.Contrast(img).enhance(1.05)
        img = ImageEnhance.Color(img).enhance(1.08)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
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
    }
    if settings.image_enhance:
        params["enhance"] = "true"
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
