"""Thin wrapper around the Gemini text model with JSON helpers."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

_client_cache: dict[str, Any] = {}


def _get_client():
    settings.validate_text()
    key = settings.gemini_api_key
    if key in _client_cache:
        return _client_cache[key]
    from google import genai  # imported lazily so the dependency stays optional

    client = genai.Client(api_key=key)
    _client_cache[key] = client
    return client


def generate_text(prompt: str, *, temperature: float = 0.9) -> str:
    """Return a plain-text completion from Gemini."""
    from google.genai import types

    client = _get_client()
    response = client.models.generate_content(
        model=settings.gemini_text_model,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    return (response.text or "").strip()


def _extract_json(text: str) -> str:
    """Pull a JSON object/array out of a possibly fenced model response."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    start = min(
        (i for i in (text.find("{"), text.find("[")) if i != -1),
        default=-1,
    )
    if start != -1:
        end = max(text.rfind("}"), text.rfind("]"))
        if end > start:
            return text[start : end + 1].strip()
    return text.strip()


def generate_json(prompt: str, *, temperature: float = 0.9) -> Any:
    """Generate text and parse it as JSON, tolerating code fences/prose."""
    raw = generate_text(prompt, temperature=temperature)
    payload = _extract_json(raw)
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        logger.error("Failed to parse JSON from model output:\n%s", raw)
        raise ValueError(f"Model did not return valid JSON: {exc}") from exc
