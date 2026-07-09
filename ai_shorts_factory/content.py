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

import datetime as dt
import json
import logging
import random

from . import optimizer
from .config import OUTPUT_DIR, settings
from .llm import generate_json, generate_text
from .models import Scene, VideoMetadata

logger = logging.getLogger(__name__)

# The channel's voice. Every theme inherits this tone so visuals + narration
# stay cohesive no matter which subject/format is picked.
_CHANNEL_IDENTITY = (
    "a faceless, cinematic channel that triggers awe and a little dread with "
    "curiosity-driven science, space, nature, the deep ocean, the human body, "
    "history, psychology, technology, unsolved mysteries, strange creatures, "
    "mythology, ancient civilizations, medical anatomy, unexplained phenomena "
    "and the far future. Dark, ominous, jaw-dropping, scientifically grounded "
    "but dramatic"
)

# Viral psychology identity (default): human behavior content for a 16-35,
# English-speaking Shorts audience — the fastest-monetizing faceless niche.
_PSYCH_IDENTITY = (
    "a faceless, cinematic channel about the psychology of human behavior — "
    "attraction, dark psychology, brain science, emotions, relationships, "
    "cognitive biases, habits and self-improvement. Every video makes a 16-35 "
    "year old viewer feel personally seen ('this is literally me'), taps "
    "curiosity, fear, attraction, mystery and relatability, and is "
    "scientifically grounded but emotionally charged"
)

THEME_DESCRIPTIONS = {
    # Default theme: viral psychology (fastest monetization niche).
    "viral-psychology": _PSYCH_IDENTITY,
    # Umbrella theme: broad science/curiosity subjects, single cohesive tone.
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
    # Core curiosity formats
    "a shocking 'What If' hypothetical scenario",
    "a terrifying real scientific fact almost nobody knows",
    "an unsolved mystery that science still cannot explain",
    "a mind-bending 'Why does...' question about reality",
    "a chilling, evidence-based prediction about the future",
    "a jaw-dropping discovery scientists actually made",
    "a cosmic-scale comparison that makes the viewer feel tiny",
    "a 'this is happening right now and you don't notice it' reveal",
    "a 'Top 3 most disturbing/bizarre/strange' ranked list",
    "a 'scientists can't explain this' anomaly",
    "a '10-second fact that will change how you see the world'",
    "a dramatic before-and-after transformation (time, evolution, decay)",
    "a 'you wouldn't survive 5 seconds here' extreme environment",
    "a 'this was hidden from the public for decades' reveal",
    "a 'what would happen to your body if...' scenario",
    "a 'the real reason why...' counterintuitive explanation",
    "a '99% of people don't know this' elite-knowledge reveal",
    "a rapid-fire '3 facts in 20 seconds' micro-list",
    "a 'your brain can't process this' perception-breaking visual fact",
    "a 'this happens every X seconds and nobody notices' revelation",
    # Myth vs. Truth (cognitive dissonance hook — high retention format)
    "a 'everyone thinks X but the truth is Y' myth-busting reveal",
    # Countdown tension (numbered stakes build suspense)
    "a countdown of the '3 most terrifying/impossible/forbidden' things",
    # Story hook + reveal (tease mystery, deliver payoff)
    "a 'scientists discovered something they weren't supposed to find' reveal",
    # Scale/size comparison (proven viral format)
    "a mind-blowing size or scale comparison that reframes reality",
    # Medical/body mechanism (highest CPM niche)
    "a 'this is what happens inside your body when...' medical reveal",
    # Ancient mystery (mythology crossover)
    "an ancient myth that turned out to be scientifically accurate",
    # Perception/optical illusion
    "a 'you've been seeing this wrong your entire life' perception shift",
    # Extreme statistics
    "a statistic so extreme it sounds fake but is scientifically proven",
]

# Subject areas grouped by CATEGORY. The category cooldown system ensures we
# don't repeat the same category within 7 days (prevents audience fatigue and
# algorithmic self-competition).
_SUBJECT_CATEGORIES: dict[str, list[str]] = {
    "space": [
        "black holes, dying stars and the end of the universe",
        "the edge of the observable universe and what lies beyond",
        "alien life and the Fermi paradox",
        "the Sun and what it does to Earth",
        "neutron stars, pulsars and magnetars",
        "rogue planets drifting alone through interstellar space",
        "cosmic collisions, galaxy mergers and stellar explosions",
        "the cosmic microwave background and echoes of the Big Bang",
    ],
    "ocean": [
        "the deep ocean and what lurks in the abyss",
        "underwater volcanoes and hydrothermal vents",
        "bioluminescent creatures in the midnight zone",
        "ocean sounds, the Bloop, and unexplained underwater signals",
        "shipwrecks, sunken cities and what the ocean has swallowed",
    ],
    "earth": [
        "Earth's violent past and mass extinctions",
        "natural disasters, supervolcanoes and planetary catastrophe",
        "ancient Earth, lost worlds and deep time",
        "extreme weather phenomena (ball lightning, fire tornadoes, ice storms)",
        "Earth's magnetic field, pole reversals and geomagnetic storms",
    ],
    "body": [
        "the human brain, consciousness and perception",
        "diseases, parasites, viruses and the fragility of life",
        "the limits of the human body (pressure, cold, speed, pain)",
        "sleep, dreams and what happens when the brain shuts down",
        "what happens inside your body during extreme stress or fear",
        "the immune system at war: how your body fights invaders",
        "human anatomy surprises most people don't know about",
    ],
    "history": [
        "lost civilizations and ancient mysteries (Egypt, Maya, Göbekli Tepe)",
        "forbidden experiments and banned science throughout history",
        "history's strangest disappearances and unsolved cases",
        "ancient engineering that shouldn't have been possible",
        "classified projects and experiments governments hid for decades",
    ],
    "psychology": [
        "the science of fear, phobias and the uncanny valley",
        "cognitive biases and how your brain lies to you",
        "the psychology of cults, manipulation and mass hysteria",
        "why your brain creates false memories and déjà vu",
        "the psychology of decision-making under extreme pressure",
    ],
    "technology": [
        "future technology, AI and the fate of civilization",
        "deepfakes, surveillance and the death of privacy",
        "nuclear weapons, radiation and forbidden zones",
        "abandoned megaprojects and technology the world gave up on",
    ],
    "physics": [
        "time, gravity, relativity and the limits of physics",
        "quantum mechanics and the weirdness of reality",
        "parallel universes, simulation theory and the multiverse",
        "the speed of light and what would happen if you could break it",
        "antimatter, dark matter and the invisible universe",
    ],
    "creatures": [
        "the most bizarre creatures evolution ever created",
        "extremophiles, tardigrades and life in impossible places",
        "prehistoric monsters and the creatures that ruled before us",
        "parasites that hijack their host's brain and behavior",
        "deep sea giants and creatures we've barely ever filmed",
    ],
    "places": [
        "the world's most dangerous and forbidden places",
        "Chernobyl, abandoned cities and places humans left behind",
        "places on Earth that look like alien worlds",
    ],
    "survival": [
        "water, food, resources and the coming scarcity crisis",
        "what happens to the human body in extreme environments",
    ],
    "mythology": [
        "Greek gods, titans and the wars that shaped Olympus",
        "Norse mythology: Ragnarök, Odin, Thor and the World Tree",
        "Egyptian gods, the afterlife and the Book of the Dead",
        "ancient myths that turned out to match real science",
        "mythological creatures that may have been based on real animals",
    ],
    "unexplained": [
        "unexplained signals, lights and phenomena science can't solve",
        "the Wow! signal, Hessdalen lights and other anomalies",
        "numbers stations, coded transmissions and mysterious broadcasts",
        "objects and artifacts that shouldn't exist (out-of-place artifacts)",
    ],
    "medical": [
        "rare medical conditions that seem impossible",
        "what happens to organs during surgery, trauma or extreme cold",
        "the microbiome: trillions of organisms living inside you",
        "how anesthesia works (and why we still don't fully understand it)",
    ],
    "scale": [
        "size comparisons: atoms to galaxies and everything between",
        "speed comparisons: from a snail to the speed of light",
        "time comparisons: human history vs the age of the universe",
        "energy comparisons: a heartbeat vs a supernova",
    ],
}

# Psychology formats: every angle triggers curiosity, fear, attraction,
# mystery, emotional impact or relatability.
_PSYCH_FORMATS = [
    "a 'Why you...' hyper-relatable behavior explanation",
    "a 'Why smart people...' counterintuitive psychology reveal",
    "a dark psychology tactic people use on you without you noticing",
    "the hidden psychology behind a universal relationship experience",
    "a 'your brain does this and you can't stop it' brain-science reveal",
    "a psychological sign almost everyone misreads",
    "a cognitive bias that secretly controls your decisions",
    "the real reason an emotionally painful experience happens",
    "a 'psychologists found...' study result that feels personal",
    "a '99% of people don't know why they do this' behavior reveal",
    "a psychology-of-attraction mechanism that feels forbidden to know",
    "a 'this is why you can't stop thinking about them' emotional loop",
    "a manipulation red flag disguised as normal behavior",
    "a habit-loop mechanism that explains a daily struggle",
    "a 'your childhood explains this' developmental psychology reveal",
    "a 'people who do X are actually Y' personality decoder",
    "a social-behavior rule everyone follows without realizing",
    "a 'why rejection/ghosting physically hurts' neuroscience reveal",
]

_PSYCH_SUBJECT_CATEGORIES: dict[str, list[str]] = {
    "attraction": [
        "the psychology of attraction and desire",
        "why you can't stop thinking about someone",
        "what makes people instantly likeable or magnetic",
        "the science of chemistry, eye contact and body language",
        "why playing hard to get works (and when it backfires)",
    ],
    "relationships": [
        "why people suddenly lose interest",
        "the psychology behind ghosting and breadcrumbing",
        "why you miss people who hurt you",
        "attachment styles and why you love the way you do",
        "why couples fight about nothing",
    ],
    "dark-psychology": [
        "how narcissists and manipulators actually operate",
        "gaslighting, love bombing and covert control tactics",
        "psychological tricks salespeople and apps use on you",
        "why cult leaders and con artists are so convincing",
        "red flags disguised as charm",
    ],
    "brain": [
        "why your brain replays embarrassing memories at night",
        "how dopamine hijacks your motivation and focus",
        "why your brain sabotages you before big moments",
        "memory glitches: déjà vu, false memories, blackouts",
        "what anxiety and overthinking physically do to your brain",
    ],
    "emotions": [
        "why humans need validation",
        "why embarrassment, shame and guilt feel physically painful",
        "why crying, venting and music actually regulate emotions",
        "emotional numbness and why you feel nothing sometimes",
        "why loneliness is as harmful as smoking",
    ],
    "social": [
        "why smart people overthink and stay quiet in groups",
        "the psychology of first impressions and status games",
        "why people act differently online vs in person",
        "herd behavior: why crowds make you dumber",
        "why we copy the people we admire",
    ],
    "biases": [
        "cognitive biases that control your money decisions",
        "why you think you're right even when you're wrong",
        "the spotlight effect: nobody notices you as much as you think",
        "why first information anchors everything you believe",
        "survivorship bias and why success advice is broken",
    ],
    "habits": [
        "why bad habits are so hard to break",
        "the psychology of procrastination and instant gratification",
        "how tiny habits rewire identity",
        "why motivation dies and discipline wins",
        "doomscrolling: why you can't put the phone down",
    ],
    "self-improvement": [
        "why comparing yourself to others destroys you",
        "impostor syndrome and why success feels fake",
        "the psychology of confidence and self-sabotage",
        "why your comfort zone shrinks when unused",
        "how your self-talk rewires your future behavior",
    ],
}


def _is_psych_theme() -> bool:
    return settings.content_theme == "viral-psychology"


def _active_formats() -> list[str]:
    return _PSYCH_FORMATS if _is_psych_theme() else _CONTENT_FORMATS


def _active_categories() -> dict[str, list[str]]:
    return _PSYCH_SUBJECT_CATEGORIES if _is_psych_theme() else _SUBJECT_CATEGORIES


# Flat list for backwards compatibility.
_SUBJECT_SEEDS = [
    seed for seeds in _SUBJECT_CATEGORIES.values() for seed in seeds
]

_CATEGORY_COOLDOWN_DAYS = 5
_CATEGORY_HISTORY_FILE = OUTPUT_DIR / "category_history.json"


def _load_category_history() -> dict[str, str]:
    """Return {category: last_used_iso_date}."""
    if not _CATEGORY_HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(_CATEGORY_HISTORY_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _record_category(category: str) -> None:
    history = _load_category_history()
    history[category] = dt.date.today().isoformat()
    _CATEGORY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CATEGORY_HISTORY_FILE.write_text(
        json.dumps(history, indent=2), encoding="utf-8"
    )


def _pick_subject_with_cooldown() -> tuple[str, str]:
    """Pick a subject respecting category cooldown. Returns (subject, category).

    Categories are sampled proportionally to learned performance weights
    (self-improvement loop), so winning categories appear more often.
    """
    categories = _active_categories()
    history = _load_category_history()
    today = dt.date.today()
    available_categories: list[str] = []
    for cat, last_used in history.items():
        if cat not in categories:
            continue
        try:
            last_date = dt.date.fromisoformat(last_used)
        except ValueError:
            available_categories.append(cat)
            continue
        if (today - last_date).days >= _CATEGORY_COOLDOWN_DAYS:
            available_categories.append(cat)
    # Add categories never used before.
    for cat in categories:
        if cat not in history:
            available_categories.append(cat)
    # If all categories are on cooldown, pick the oldest one.
    if not available_categories:
        used = {c: d for c, d in history.items() if c in categories} or history
        oldest_cat = min(used, key=lambda c: used[c])
        available_categories = [oldest_cat]
    weights = optimizer.category_weights()
    w = [weights.get(cat, 1.0) for cat in available_categories]
    category = random.choices(available_categories, weights=w, k=1)[0]
    if category not in categories:
        category = random.choice(list(categories))
    subject = random.choice(categories[category])
    return subject, category

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
    "The Parasite That Controls Its Host's Mind",
    "Ancient Greeks Knew This 2000 Years Early",
    "Your Body Does This Every 7 Seconds",
    "The Place On Earth Where Gravity Breaks",
    "Why Anesthesia Still Baffles Scientists",
    "Norse Gods Predicted This Real Disaster",
    "3 Signals From Space We Can't Explain",
    "The Size Of A Neutron Star Will Haunt You",
    "What Happens Inside You During A Panic Attack",
    "The Ancient City Hidden Under The Ocean",
]


def _theme_text() -> str:
    return THEME_DESCRIPTIONS.get(settings.content_theme, settings.content_theme)


def generate_topic(avoid: list[str] | None = None) -> str:
    """Generate a single viral, on-brand Short topic.

    A random *format* and *subject* are sampled (respecting category cooldown)
    then Gemini fuses them into one irresistible, scroll-stopping title that
    still fits the channel identity.
    """
    avoid = avoid or []
    if not settings.gemini_api_key:
        logger.warning("No GEMINI_API_KEY set; using fallback topic list.")
        choices = [t for t in _FALLBACK_TOPICS if t not in avoid] or _FALLBACK_TOPICS
        return random.choice(choices)

    fmt = random.choice(_active_formats())
    subject, category = _pick_subject_with_cooldown()
    _record_category(category)
    logger.info("Category: %s | Subject: %s", category, subject)

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
        "- Use a SPECIFIC number, measurement, or concrete detail when natural.\n"
        "- The title alone should make someone NEED to know what happens next.\n"
        "- 4-8 words, Title Case, no quotes, NO EMOJIS, no clickbait lies.\n"
        "- Where natural, include a long-tail phrase people actually search "
        "(3+ words, specific, low competition) so the video also ranks in "
        "search, not just the Shorts feed.\n"
        "- The title MUST make the viewer feel they'll learn something others "
        "don't know — the #1 share trigger for science content is making "
        "viewers feel intelligent.\n"
        "- Do NOT start with generic 'What If' unless the scenario is ultra-specific.\n"
        "- NEVER produce fiction, storytelling, series episodes, character-based\n"
        "  narratives, mystery stories, or any non-factual entertainment content.\n"
        "  Stay strictly within real science, real phenomena, real facts.\n"
        f"- Language: {settings.content_language}.\n"
        f"{avoid_block}\n"
        f"{_retention_feedback_block()}\n"
        "Return ONLY the title text, nothing else."
    )
    best_title = ""
    best_total = -1.0
    attempts = max(1, settings.topic_attempts) if settings.quality_gates else 1
    for attempt in range(attempts):
        title = (
            generate_text(prompt, temperature=1.05).splitlines()[0].strip().strip('"')
        )
        if not title:
            continue
        if not settings.quality_gates:
            best_title = title
            break
        scores = score_topic(title)
        total = _weighted_topic_score(scores)
        logger.info("Topic candidate %d: %r scored %s", attempt + 1, title, scores)
        if total > best_total:
            best_title, best_total = title, total
        if (
            scores.get("virality", 0) >= settings.min_virality_score
            and scores.get("emotional_impact", 0) >= settings.min_emotional_impact
            and scores.get("retention", 0) >= settings.min_retention_prediction
            and scores.get("monetization", 0) >= settings.min_ctr_prediction
        ):
            best_title = title
            break
        logger.info("Topic rejected by quality gate; regenerating.")
    title = best_title or random.choice(_FALLBACK_TOPICS)
    optimizer.record_generation(title, category, fmt)
    return title


# Monetization counts extra when choosing between candidates: high-RPM topics
# reach payout faster at the same view count.
_TOPIC_SCORE_WEIGHTS = {
    "virality": 1.0,
    "retention": 1.0,
    "emotional_impact": 1.0,
    "monetization": 1.5,
}


def _weighted_topic_score(scores: dict[str, int]) -> float:
    total_weight = sum(_TOPIC_SCORE_WEIGHTS.get(k, 1.0) for k in scores)
    if not total_weight:
        return 0.0
    return (
        sum(v * _TOPIC_SCORE_WEIGHTS.get(k, 1.0) for k, v in scores.items())
        / total_weight
    )


def score_topic(topic: str) -> dict[str, int]:
    """Score a topic candidate 0-100 on virality, retention, emotion, monetization."""
    prompt = (
        "You are a brutally honest YouTube Shorts performance analyst for "
        f"{_theme_text()}.\n"
        f'Score this Short topic: "{topic}"\n\n'
        "Judge against the best-performing Shorts in this niche (16-35, "
        "English-speaking audience). Be strict — an average topic scores 60-75; "
        "only genuinely scroll-stopping topics score 85+.\n"
        "Return ONLY a JSON object with integer keys 0-100:\n"
        '- "virality": curiosity gap strength + shareability\n'
        '- "retention": how likely viewers watch to the end\n'
        '- "emotional_impact": fear/attraction/relatability intensity\n'
        '- "monetization": advertiser-friendliness + CPM potential\n'
    )
    try:
        data = generate_json(prompt, temperature=0.2)
        return {
            k: int(data.get(k, 0))
            for k in ("virality", "retention", "emotional_impact", "monetization")
        }
    except Exception as exc:  # scoring must never break generation
        logger.warning("Topic scoring failed (%s); accepting candidate.", exc)
        return {"virality": 100, "retention": 100, "emotional_impact": 100, "monetization": 100}


def _retention_feedback_block() -> str:
    """Prompt addendum from the self-learning loop (empty when performance is fine)."""
    try:
        feedback = optimizer.retention_feedback()
    except Exception as exc:  # learning must never break generation
        logger.warning("Retention feedback unavailable: %s", exc)
        return ""
    return f"\n{feedback}\n" if feedback else ""


def generate_hooks(topic: str) -> str:
    """Generate 5 hook candidates with predicted CTR and return the best one."""
    prompt = (
        "You are a YouTube Shorts hook specialist for "
        f"{_theme_text()}.\n"
        f'Video topic: "{topic}"\n\n'
        "Write 5 COMPLETELY DIFFERENT opening hooks (max 8 spoken words each). "
        "Each must deliver an instant shock, bold claim or curiosity gap in the "
        "first 1-3 words. No greetings, no 'imagine', no slow setups.\n"
        "For each, predict CTR-style hook quality 0-100 (how many viewers stop "
        "scrolling). Be strict: average hooks score 60-80; only irresistible "
        "hooks score 90+.\n"
        f"Language: {settings.content_language}.\n"
        f"{_retention_feedback_block()}"
        'Return ONLY a JSON array of objects: {"hook": str, "score": int}.'
    )
    try:
        data = generate_json(prompt, temperature=1.0)
        candidates = [
            (str(item.get("hook", "")).strip(), int(item.get("score", 0)))
            for item in data
            if str(item.get("hook", "")).strip()
        ]
        if not candidates:
            return ""
        hook, score = max(candidates, key=lambda c: c[1])
        logger.info("Best hook (score %d/%d min): %r", score, settings.min_hook_score, hook)
        return hook
    except Exception as exc:
        logger.warning("Hook generation failed (%s); script will self-hook.", exc)
        return ""


def predict_retention(scenes: list[Scene]) -> int:
    """Predict average retention % for a script across time segments."""
    script_text = "\n".join(f"Scene {s.index + 1}: {s.narration}" for s in scenes)
    prompt = (
        "You are a brutally honest YouTube Shorts retention analyst.\n"
        f"Script for a ~20-35 second Short:\n{script_text}\n\n"
        "Predict what % of viewers are still watching at each stage. Be strict "
        "and realistic for a small faceless channel.\n"
        "Return ONLY a JSON object with integer keys 0-100:\n"
        '"retention_0_3s", "retention_3_10s", "retention_10_20s", "retention_20_35s"'
    )
    try:
        data = generate_json(prompt, temperature=0.2)
        values = [
            int(data.get(k, 0))
            for k in (
                "retention_0_3s",
                "retention_3_10s",
                "retention_10_20s",
                "retention_20_35s",
            )
        ]
        return round(sum(values) / len(values))
    except Exception as exc:
        logger.warning("Retention prediction failed (%s); accepting script.", exc)
        return 100


def generate_script(topic: str) -> list[Scene]:
    """Generate a scene-by-scene script (narration + image prompt) for a topic."""
    n = settings.scenes_per_video
    if not settings.gemini_api_key:
        return _fallback_script(topic, n)

    hook = generate_hooks(topic) if settings.quality_gates else ""
    hook_block = (
        f'- Scene 1 narration MUST be this pre-selected winning hook: "{hook}" '
        "(you may only make tiny grammatical adjustments).\n"
        if hook
        else ""
    )
    if _is_psych_theme():
        style_line = (
            "Style: ultra-realistic cinematic photography, emotional human "
            "subjects, movie-quality dramatic lighting, moody atmosphere, "
            "shallow depth of field, vertical 9:16, no text.\n"
        )
        structure_block = (
            "- EMOTIONAL TIMELINE across the scenes: 0-2s EXTREME CURIOSITY "
            "(the hook), 2-8s EMOTIONAL CONNECTION ('this is literally you' — "
            "describe the viewer's own experience back to them), 8-18s the "
            "EXPLANATION (the psychological mechanism, named simply), 18-25s "
            "the TWIST (a counterintuitive reveal that reframes everything), "
            "final seconds a QUESTION or SHOCK ending.\n"
        )
    else:
        style_line = (
            "Style: photorealistic cinematic CGI, dark dramatic mood, vertical "
            "9:16, no text, no people's faces.\n"
        )
        structure_block = ""

    duration_text = "20-35" if _is_psych_theme() else "20-25"
    prompt = (
        "You are an elite YouTube Shorts scriptwriter for "
        f"{_theme_text()}.\n\n"
        f'Write a script for a ~{duration_text} second vertical Short titled: "{topic}".\n\n'
        "Engineer it for the 2026 Shorts algorithm. Key metrics: average view "
        "duration MUST exceed 80% of video length (the algorithm threshold for "
        "expanded reach), loop rate 1.2x+, and viewed-vs-swiped ratio above 75%. "
        "Every replay counts as a new view, so LOOP STRUCTURE is the #1 priority "
        "after the hook. Hard rules:\n"
        f"- Exactly {n} scenes.\n"
        f"{hook_block}"
        f"{structure_block}"
        "- SCENE 1 = THE HOOK (max 8 words). The first 2-3 spoken words must "
        "deliver an instant shock, bold claim or curiosity gap — the algorithm "
        "tests viewer reaction in the first 1-3 seconds. State the most "
        "fascinating promise immediately. NEVER start with a greeting, 'imagine', "
        "'picture this', or any slow setup. Scene 1's image_prompt MUST describe "
        "the single most striking, jaw-dropping visual of the entire video — the "
        "first 0.5 seconds decides viewed-vs-swiped, so save nothing for later.\n"
        "- SCENE 2 = RE-HOOK + ESCALATION: deepen the mystery or raise stakes "
        "with a pattern-interrupt (unexpected twist, contradiction). Include ONE "
        "specific surprising number or measurement.\n"
        "- SCENE 3 = PEAK PAYOFF: deliver the most jaw-dropping fact. This is "
        "the 'hump' that maximises the retention curve mid-video and triggers "
        "shares. Make the viewer feel smart for watching — this emotion drives "
        "the most shares in science content.\n"
        "- FINAL scene = LOOP TRIGGER + COMMENT CTA: end with a haunting open "
        "question or mind-bending callback that DIRECTLY references the hook's "
        "imagery or claim, so when the video replays the viewer feels a seamless "
        "loop and watches again. The LAST sentence MUST be a short provocative "
        "question that DEMANDS a comment (e.g. 'Would you survive?' / 'What "
        "would you choose?' / 'How long would you last?'). The last 3-4 words "
        "should feel like a lead-in to the first words.\n"
        "- COMMENT-BAIT DETAIL: deliberately leave ONE small, concrete detail "
        "open, unresolved or mildly debatable (a number people will want to "
        "verify, a claim experts disagree on, an unanswered 'but how?') so "
        "viewers feel compelled to comment. Never state false facts — leave a "
        "true detail incomplete instead.\n"
        "- Every narration line is 1-2 SHORT punchy spoken sentences. NO filler "
        "words, no 'in this video', no calls to like/subscribe. Keep total word "
        f"count VERY low (under {'85' if _is_psych_theme() else '55'} words total) "
        "— brevity = higher retention %. "
        f"The {duration_text} second range has the highest algorithm performance in 2026.\n"
        f"- Language: {settings.content_language}.\n"
        "- For each scene write a DETAILED, SPECIFIC AI IMAGE PROMPT (English). "
        "Include: exact subject/action, specific camera angle (e.g. extreme "
        "close-up, wide establishing shot, low-angle), lighting type (e.g. rim "
        "light, god-rays, bioluminescence), color palette, atmosphere/particles "
        "(dust, fog, embers). Each scene's visual MUST be dramatically different "
        "from the previous one (different scale, different palette, different "
        "angle) to maintain stimulus density — at least 1 visual change every "
        "2-3 seconds prevents viewer fatigue. "
        f"{style_line}"
        "- 'on_screen_text': for SCENE 1 this MUST be a bold 2-4 word hook that "
        "captures the video's core shock/question (this will be rendered as a "
        "large overlay to catch silent viewers). For other scenes, a punchy "
        "2-4 word caption that adds a micro-payoff even on mute.\n"
        f"{_retention_feedback_block()}\n"
        "Return ONLY a JSON array of objects with keys: "
        '"narration", "image_prompt", "on_screen_text".'
    )
    attempts = max(1, settings.script_attempts) if settings.quality_gates else 1
    best_scenes: list[Scene] = []
    best_retention = -1
    for attempt in range(attempts):
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
            continue
        if not settings.quality_gates:
            return scenes
        retention = predict_retention(scenes)
        logger.info(
            "Script attempt %d predicted retention: %d%% (min %d%%)",
            attempt + 1,
            retention,
            settings.min_retention_prediction,
        )
        if retention > best_retention:
            best_scenes, best_retention = scenes, retention
        if retention >= settings.min_retention_prediction:
            return scenes
        logger.info("Script below retention gate; regenerating.")
    if not best_scenes:
        raise ValueError("Script generation returned no usable scenes.")
    return best_scenes


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
        '- "title": 50-60 chars ideal (never over 70), curiosity-driven; '
        "title only, no quotes, NO EMOJIS. Use a specific number or detail and "
        "one power word (e.g. 'hidden', 'secret', 'truth', 'never'). Serve "
        "BOTH browse and search: put the main search keyword phrase in the "
        "FIRST 3 words, then the emotional hook. Prefer a long-tail keyword "
        "phrase (3+ words) people actually type.\n"
        '- "description": The FIRST 2 sentences must contain the main search '
        "keyword naturally — only they appear in search results. Sentence 1 is "
        "the hook, sentence 2 adds context. Then a DIRECT engagement question "
        "that begs a comment (e.g. "
        "'Would you survive this? Tell us in the comments 👇' or 'What would you "
        "do first? Drop your answer below'). End with 4-5 relevant hashtags "
        "including #shorts. Include 2-3 hashtags in Turkish that match the "
        "topic (e.g. #bilim #uzay #evren #ger\u00e7ekler) to capture the Turkish "
        "audience alongside the global English audience.\n"
        '- "tags": array of 15-18 lowercase keyword strings, structured as: '
        "3-5 BROAD English terms (e.g. 'psychology', 'science facts'), then "
        "7-10 LONG-TAIL English phrases of 3+ words that people actually "
        "search (specific, low competition — e.g. 'why you overthink at "
        "night'), then 3-4 Turkish equivalents (e.g. 'psikoloji', 'ilgin\u00e7 "
        "bilgiler') to capture both audiences.\n"
        '- "pinned_comment": ONE short provocative question about THIS video, '
        "crafted to start a debate in the comments — target a detail people "
        "will disagree about or want to answer from their own experience. "
        "End with '\U0001f447'. Max 100 chars.\n"
    )
    data = generate_json(prompt, temperature=0.8)
    title = str(data.get("title", topic))[:100]
    description = str(data.get("description", topic))
    tags = [str(t) for t in data.get("tags", [])][:20]
    if "shorts" not in [t.lower() for t in tags]:
        tags.append("shorts")
    pinned_comment = str(data.get("pinned_comment", "")).strip()[:200]
    return VideoMetadata(
        title=title,
        description=description,
        tags=tags,
        pinned_comment=pinned_comment,
    )


def _fallback_script(topic: str, n: int) -> list[Scene]:
    lines = [
        (f"{topic}", "ominous cinematic wide shot establishing the scenario", topic[:24]),
        (
            "Within seconds, everything starts to break down.",
            "chaos unfolding, dramatic destruction, photorealistic",
            "It begins",
        ),
        (
            "Scientists say the consequences would be catastrophic.",
            "scientists looking at data screens, tense atmosphere",
            "Catastrophe",
        ),
        (
            "So next time you look up, remember how fragile it all is. Would you survive?",
            "lone figure looking at vast dramatic sky, hopeful yet ominous",
            "Would you?",
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
