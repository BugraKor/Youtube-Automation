"""Topic, script, scene and metadata generation using Gemini.

The prompts here are tuned for the YouTube Shorts algorithm. The two signals
that matter most for a faceless Short are:

* **Viewed vs. swiped** — since 2025 a view is counted the moment a Short
  *starts or replays*, and "engaged views" track who keeps watching. So the
  first ~1 second must stop the scroll, and the ending must loop back to the
  hook to trigger replays.
* **Retention + shares/comments** — tension has to escalate with concrete,
  surprising specifics, and the Short should end on a question that begs a
  comment or a re-share.

Topics stay inside one cohesive channel identity (dark, cinematic, awe/dread
curiosity about science, space, nature, the future and the unexplained) but
rotate across several proven curiosity *formats* and *subjects* so the channel
keeps broadening without drifting off-brand.
"""

from __future__ import annotations

import logging
import random

from .config import settings
from .llm import generate_json, generate_text
from .models import Scene, VideoMetadata

logger = logging.getLogger(__name__)

# The channel's voice. Every theme inherits this tone so visuals + narration
# stay cohesive no matter which subject/format is picked.
_CHANNEL_IDENTITY = (
    "a faceless, cinematic channel that triggers awe and a little dread with "
    "curiosity-driven science, space, nature, the deep ocean, the human body, "
    "the far future and unexplained mysteries. Dark, ominous, jaw-dropping, "
    "scientifically grounded but dramatic"
)

THEME_DESCRIPTIONS = {
    # Umbrella theme: broad subjects, single cohesive tone (default).
    "mixed-curiosity": _CHANNEL_IDENTITY,
    # Kept for backwards compatibility; now part of the wider identity.
    "what-if-disaster": (
        "shocking 'What If' disaster and catastrophe scenarios about science, "
        "space, nature and the future. Curiosity-driven, slightly ominous, "
        "scientifically grounded but dramatic"
    ),
    "space-mysteries": (
        "mind-bending space and cosmos mysteries — black holes, dying stars, "
        "the scale of the universe, alien life. Awe-inspiring and ominous"
    ),
    "deep-ocean": (
        "the terrifying deep ocean and what hides in the dark — creatures, "
        "pressure, the unexplored abyss. Eerie, suspenseful, scientific"
    ),
}

# Proven high-curiosity Short *formats*. We rotate through these so the feed
# does not feel repetitive while staying inside the channel identity.
_CONTENT_FORMATS = [
    "a shocking 'What If' hypothetical scenario",
    "a terrifying real scientific fact almost nobody knows",
    "an unsolved mystery that science still cannot explain",
    "a mind-bending 'Why does...' question about reality",
    "a chilling, evidence-based prediction about the future",
    "a jaw-dropping discovery scientists actually made",
    "a cosmic-scale comparison that makes the viewer feel tiny",
    "a 'this is happening right now and you don't notice it' reveal",
]

# Fresh subject areas, so two videos in a row are rarely about the same thing.
_SUBJECT_SEEDS = [
    "black holes, dying stars and the end of the universe",
    "the deep ocean and what lurks in the abyss",
    "the Sun and what it does to Earth",
    "Earth's violent past and mass extinctions",
    "the human brain, body and consciousness",
    "time, gravity and the limits of physics",
    "alien life and the Fermi paradox",
    "future technology, AI and the fate of civilization",
    "natural disasters and planetary catastrophe",
    "ancient Earth, lost worlds and deep time",
    "the edge of the observable universe",
    "diseases, parasites and the fragility of life",
]

# Used only as a no-API-key fallback so the pipeline still runs. Broadened so it
# already spans the wider channel identity, not just disasters.
_FALLBACK_TOPICS = [
    "What If The Sun Disappeared For 24 Hours?",
    "The Deepest Sound Ever Recorded In The Ocean",
    "What If You Fell Into A Black Hole?",
    "The Day The Earth Nearly Lost Its Atmosphere",
    "Why Your Brain Deletes Most Of Reality",
    "What If Gravity Stopped For One Second?",
    "The Star That Could Erase Half The Sky",
    "What Lives At The Bottom Of The Ocean?",
    "The Signal From Space No One Can Explain",
    "What If Earth Stopped Spinning Right Now?",
]


def _theme_text() -> str:
    return THEME_DESCRIPTIONS.get(settings.content_theme, settings.content_theme)


def generate_topic(avoid: list[str] | None = None) -> str:
    """Generate a single viral, on-brand Short topic.

    A random *format* and *subject* are sampled to push variety, then Gemini
    fuses them into one irresistible, scroll-stopping title that still fits the
    channel identity.
    """
    avoid = avoid or []
    if not settings.gemini_api_key:
        logger.warning("No GEMINI_API_KEY set; using fallback topic list.")
        choices = [t for t in _FALLBACK_TOPICS if t not in avoid] or _FALLBACK_TOPICS
        return random.choice(choices)

    fmt = random.choice(_CONTENT_FORMATS)
    subject = random.choice(_SUBJECT_SEEDS)

    avoid_block = ""
    if avoid:
        avoid_block = (
            "\nDo NOT repeat or closely resemble any of these recent titles:\n- "
            + "\n- ".join(avoid[-25:])
        )
    prompt = (
        f"You are a viral YouTube Shorts strategist for {_theme_text()}.\n\n"
        f"This video's angle: {fmt}.\n"
        f"This video's subject area: {subject}.\n\n"
        "Write ONE scroll-stopping Short title. Requirements:\n"
        "- Open a curiosity gap the viewer cannot leave unanswered.\n"
        "- Front-load the most shocking/intriguing word in the first 1-3 words.\n"
        "- Prefer concrete specifics or numbers over vague words when natural.\n"
        "- The title alone should make someone NEED to know what happens next.\n"
        "- 4-8 words, Title Case, no quotes, no emojis, no clickbait lies.\n"
        f"- Language: {settings.content_language}.\n"
        f"{avoid_block}\n\n"
        "Return ONLY the title text, nothing else."
    )
    title = generate_text(prompt, temperature=1.05).splitlines()[0].strip().strip('"')
    return title or random.choice(_FALLBACK_TOPICS)


def generate_script(topic: str) -> list[Scene]:
    """Generate a scene-by-scene script (narration + image prompt) for a topic."""
    n = settings.scenes_per_video
    if not settings.gemini_api_key:
        return _fallback_script(topic, n)

    prompt = (
        "You are an elite YouTube Shorts scriptwriter for "
        f"{_theme_text()}.\n\n"
        f'Write a script for a ~30-40 second vertical Short titled: "{topic}".\n\n'
        "Engineer it for the Shorts algorithm. Every replay counts as a new view "
        "(since March 2025), so LOOP STRUCTURE is the #1 priority after the "
        "hook. Hard rules:\n"
        f"- Exactly {n} scenes.\n"
        "- SCENE 1 = THE HOOK. The first 3-4 spoken words must deliver an "
        "instant shock, bold claim or curiosity gap. State the most fascinating "
        "promise immediately. Max 10 words total. NEVER start with a greeting, "
        "'imagine', 'picture this', or any slow setup.\n"
        "- SCENE 2 = RE-HOOK: deepen the mystery or raise stakes so the viewer "
        "commits. Use a pattern-interrupt (unexpected twist, contradiction).\n"
        "- MIDDLE scenes: escalate with ONE concrete, genuinely surprising "
        "fact/number per scene (real science, specific numbers, no vague filler). "
        "Each scene must add new information — never repeat what was said.\n"
        "- FINAL scene = LOOP TRIGGER: end with a haunting open question or "
        "mind-bending callback that DIRECTLY references the hook's imagery or "
        "claim, so when the video replays the viewer feels a seamless loop and "
        "watches again. The last 3-4 words should feel like a lead-in to the "
        "first words. Also phrase it so people want to comment or share.\n"
        "- Every narration line is 1-2 SHORT punchy spoken sentences. NO filler "
        "words, no 'in this video', no calls to like/subscribe. Keep total word "
        "count low — brevity = higher retention %.\n"
        f"- Language: {settings.content_language}.\n"
        "- For each scene write a DETAILED, SPECIFIC AI IMAGE PROMPT (English). "
        "Include: exact subject/action, specific camera angle (e.g. extreme "
        "close-up, wide establishing shot, low-angle), lighting type (e.g. rim "
        "light, god-rays, bioluminescence), color palette, atmosphere/particles "
        "(dust, fog, embers). Make each prompt visually distinct from the others. "
        "Style: photorealistic cinematic CGI, dark dramatic mood, vertical 9:16, "
        "no text, no people's faces.\n"
        "- 'on_screen_text' is a punchy 2-4 word caption for the scene.\n\n"
        "Return ONLY a JSON array of objects with keys: "
        '"narration", "image_prompt", "on_screen_text".'
    )
    data = generate_json(prompt, temperature=0.95)
    scenes: list[Scene] = []
    for item in data:
        narration = str(item.get("narration", "")).strip()
        image_prompt = str(item.get("image_prompt", "")).strip()
        if not narration or not image_prompt:
            continue
        scenes.append(
            Scene(
                index=len(scenes),
                narration=narration,
                image_prompt=image_prompt,
                on_screen_text=str(item.get("on_screen_text", "")).strip(),
            )
        )
    if not scenes:
        raise ValueError("Script generation returned no usable scenes.")
    return scenes


def generate_metadata(topic: str, narration: str) -> VideoMetadata:
    """Generate YouTube title, description and tags optimised for discovery."""
    if not settings.gemini_api_key:
        return VideoMetadata(
            title=topic if len(topic) <= 100 else topic[:97] + "...",
            description=(
                f"{topic}\n\nWhat would you do? Comment below.\n\n"
                "#shorts #whatif #science #space"
            ),
            tags=["shorts", "what if", "science", "space", "facts", "universe"],
        )

    prompt = (
        "Create YouTube Shorts metadata optimised for discovery and clicks for a "
        f"faceless channel about {_theme_text()}.\n"
        f'Video topic: "{topic}"\n'
        f"Narration: {narration}\n\n"
        "Return ONLY a JSON object with keys:\n"
        '- "title": <=70 chars, curiosity-driven, front-load the hook word; '
        "title only, no quotes.\n"
        '- "description": a 1-sentence hook, then 1-2 sentences of context, then '
        "a question that invites comments, then 3-4 relevant hashtags ending "
        "with #shorts.\n"
        '- "tags": array of 12-15 lowercase keyword strings mixing broad and '
        "specific search terms.\n"
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
