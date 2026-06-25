"""Topic, script, scene and metadata generation using Gemini."""

from __future__ import annotations

import logging
import random

from .config import settings
from .llm import generate_json, generate_text
from .models import Scene, VideoMetadata

logger = logging.getLogger(__name__)

THEME_DESCRIPTIONS = {
    "what-if-disaster": (
        "shocking 'What If' disaster and catastrophe scenarios about science, "
        "space, nature and the future (e.g. 'What if the Sun disappeared for 24 "
        "hours?', 'What if the oceans vanished overnight?'). Curiosity-driven, "
        "slightly ominous, scientifically grounded but dramatic."
    ),
}

# Used only as a no-API-key fallback so the pipeline still runs.
_FALLBACK_TOPICS = [
    "What If The Sun Disappeared For 24 Hours?",
    "What If Earth Lost The Internet Forever?",
    "What If The Oceans Vanished Overnight?",
    "What If Gravity Doubled Tomorrow?",
    "What If The Moon Crashed Into Earth?",
    "What If All The Ice On Earth Melted Today?",
]


def _theme_text() -> str:
    return THEME_DESCRIPTIONS.get(settings.content_theme, settings.content_theme)


def generate_topic(avoid: list[str] | None = None) -> str:
    """Generate a single viral video topic for the configured theme."""
    avoid = avoid or []
    if not settings.gemini_api_key:
        logger.warning("No GEMINI_API_KEY set; using fallback topic list.")
        choices = [t for t in _FALLBACK_TOPICS if t not in avoid] or _FALLBACK_TOPICS
        return random.choice(choices)

    avoid_block = ""
    if avoid:
        avoid_block = "\nDo NOT repeat or closely resemble any of these:\n- " + "\n- ".join(
            avoid
        )
    prompt = (
        f"You are a viral YouTube Shorts strategist for a faceless channel about "
        f"{_theme_text()}\n\n"
        "Generate ONE highly clickable Short title. Requirements:\n"
        "- Provoke intense curiosity in the first 3 words.\n"
        "- 4-9 words, no quotes, no emojis, Title Case.\n"
        f"- Language: {settings.content_language}.\n"
        f"{avoid_block}\n\n"
        "Return ONLY the title text, nothing else."
    )
    title = generate_text(prompt, temperature=1.0).splitlines()[0].strip().strip('"')
    return title or random.choice(_FALLBACK_TOPICS)


def generate_script(topic: str) -> list[Scene]:
    """Generate a scene-by-scene script (narration + image prompt) for a topic."""
    n = settings.scenes_per_video
    if not settings.gemini_api_key:
        return _fallback_script(topic, n)

    prompt = (
        "You are an expert YouTube Shorts scriptwriter specialising in "
        f"high-retention faceless videos about {_theme_text()}\n\n"
        f'Write a script for a ~40 second vertical Short titled: "{topic}".\n\n'
        "Rules:\n"
        f"- Exactly {n} scenes.\n"
        "- Scene 1 is the HOOK: in the FIRST 3 words create an irresistible "
        "curiosity gap or shock so viewers cannot scroll away. <12 words.\n"
        "- Each narration line is 1-2 short, punchy spoken sentences (no filler).\n"
        "- Escalate tension scene by scene with concrete, vivid, surprising "
        "details and a real scientific consequence in the middle scenes.\n"
        "- The FINAL scene lands an ominous twist or open question that makes the "
        "video feel like it loops back to the hook (boosts replays).\n"
        f"- Language: {settings.content_language}.\n"
        "- For each scene also write a vivid, cinematic AI IMAGE PROMPT (English, "
        "photorealistic, ultra-detailed, dramatic cinematic lighting, vertical "
        "9:16 composition, no text, consistent dark dramatic mood).\n"
        "- 'on_screen_text' is a 2-5 word caption summarising the scene.\n\n"
        "Return ONLY a JSON array of objects with keys: "
        '"narration", "image_prompt", "on_screen_text".'
    )
    data = generate_json(prompt, temperature=0.95)
    scenes: list[Scene] = []
    for i, item in enumerate(data):
        scenes.append(
            Scene(
                index=i,
                narration=str(item.get("narration", "")).strip(),
                image_prompt=str(item.get("image_prompt", "")).strip(),
                on_screen_text=str(item.get("on_screen_text", "")).strip(),
            )
        )
    scenes = [s for s in scenes if s.narration and s.image_prompt]
    if not scenes:
        raise ValueError("Script generation returned no usable scenes.")
    return scenes


def generate_metadata(topic: str, narration: str) -> VideoMetadata:
    """Generate YouTube title, description and tags."""
    if not settings.gemini_api_key:
        return VideoMetadata(
            title=topic if len(topic) <= 100 else topic[:97] + "...",
            description=(
                f"{topic}\n\nA quick 'what if' thought experiment.\n\n"
                "#shorts #whatif #science #space"
            ),
            tags=["shorts", "what if", "science", "space", "disaster"],
        )

    prompt = (
        "Create YouTube Shorts metadata for a faceless channel.\n"
        f'Video topic: "{topic}"\n'
        f"Narration: {narration}\n\n"
        "Return ONLY a JSON object with keys:\n"
        '- "title": <=100 chars, curiosity-driven, include nothing but the title.\n'
        '- "description": 2-4 sentences then 3 relevant hashtags, end with #shorts.\n'
        '- "tags": array of 10-15 lowercase keyword strings.\n'
    )
    data = generate_json(prompt, temperature=0.8)
    title = str(data.get("title", topic))[:100]
    description = str(data.get("description", topic))
    tags = [str(t) for t in data.get("tags", [])][:15]
    if "shorts" not in [t.lower() for t in tags]:
        tags.append("shorts")
    return VideoMetadata(title=title, description=description, tags=tags)


def _fallback_script(topic: str, n: int) -> list[Scene]:
    lines = [
        (f"{topic}", "ominous cinematic wide shot establishing the scenario", topic[:24]),
        (
            "At first, almost nothing seems to change.",
            "eerie calm before disaster, dramatic sky",
            "The calm",
        ),
        (
            "But within hours, everything starts to break down.",
            "chaos unfolding, dramatic destruction, photorealistic",
            "It begins",
        ),
        (
            "Scientists say the consequences would be catastrophic.",
            "scientists looking at data screens, tense atmosphere",
            "Catastrophe",
        ),
        (
            "Most life as we know it could not survive.",
            "desolate apocalyptic landscape, cold lighting",
            "No survival",
        ),
        (
            "So next time you look up, remember how fragile it all is.",
            "lone figure looking at vast dramatic sky, hopeful yet ominous",
            "Stay curious",
        ),
    ]
    out: list[Scene] = []
    for i in range(n):
        narration, prompt, ost = lines[i % len(lines)]
        out.append(
            Scene(
                index=i,
                narration=narration,
                image_prompt=f"{prompt}, vertical 9:16, photorealistic, dramatic lighting",
                on_screen_text=ost,
            )
        )
    return out
