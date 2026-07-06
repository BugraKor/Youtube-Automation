"""Self-improvement loop: track published videos, learn winning patterns.

Every generated/uploaded Short is recorded in ``output/performance.json``
together with its content *category* (e.g. attraction, dark-psychology).
``refresh_stats`` pulls public view/like/comment counts via the YouTube Data
API (needs an ordinary API key — no OAuth scope changes) and computes
per-category performance weights. Topic generation then samples categories
proportionally to those weights, so the system automatically doubles down on
what performs (Phase 8) and flags high-view Shorts as long-form candidates
(Phase 9).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from .config import OUTPUT_DIR, settings

logger = logging.getLogger(__name__)

PERFORMANCE_FILE = OUTPUT_DIR / "performance.json"

# View milestones that qualify a Short topic for long-form expansion.
LONG_FORM_TIERS = [(10000, "10 minute video"), (5000, "8 minute video"), (1000, "5 minute video")]


def _load() -> list[dict[str, Any]]:
    if not PERFORMANCE_FILE.exists():
        return []
    try:
        return json.loads(PERFORMANCE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list[dict[str, Any]]) -> None:
    PERFORMANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PERFORMANCE_FILE.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def record_generation(topic: str, category: str, fmt: str) -> None:
    """Record a newly generated topic so it can later be matched to a video id."""
    entries = _load()
    entries.append(
        {
            "topic": topic,
            "category": category,
            "format": fmt,
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save(entries)


def record_upload(topic: str, video_id: str) -> None:
    """Attach the uploaded video id to the most recent entry for *topic*."""
    entries = _load()
    for entry in reversed(entries):
        if entry.get("topic") == topic and not entry.get("video_id"):
            entry["video_id"] = video_id
            break
    else:
        entries.append(
            {
                "topic": topic,
                "video_id": video_id,
                "created_at": dt.datetime.now().isoformat(timespec="seconds"),
            }
        )
    _save(entries)


def refresh_stats() -> list[dict[str, Any]]:
    """Refresh public statistics for all recorded videos. Needs YOUTUBE_API_KEY."""
    if not settings.youtube_api_key:
        logger.info("YOUTUBE_API_KEY not set; skipping stats refresh.")
        return _load()

    from googleapiclient.discovery import build

    entries = _load()
    ids = [e["video_id"] for e in entries if e.get("video_id")]
    if not ids:
        return entries

    youtube = build("youtube", "v3", developerKey=settings.youtube_api_key)
    stats: dict[str, dict[str, Any]] = {}
    for i in range(0, len(ids), 50):
        response = (
            youtube.videos()
            .list(part="statistics", id=",".join(ids[i : i + 50]))
            .execute()
        )
        for item in response.get("items", []):
            stats[item["id"]] = item.get("statistics", {})

    now = dt.datetime.now().isoformat(timespec="seconds")
    for entry in entries:
        s = stats.get(entry.get("video_id", ""))
        if not s:
            continue
        entry["views"] = int(s.get("viewCount", 0))
        entry["likes"] = int(s.get("likeCount", 0))
        entry["comments"] = int(s.get("commentCount", 0))
        entry["stats_updated_at"] = now
    _save(entries)
    return entries


def category_weights() -> dict[str, float]:
    """Return {category: weight} learned from past performance.

    Weight = category's average views relative to the overall average, clamped
    to [0.5, 3.0] so no category is ever fully starved and winners are boosted
    up to 3x. Categories without data get weight 1.0.
    """
    entries = [e for e in _load() if e.get("category") and "views" in e]
    if len(entries) < 5:  # not enough signal yet
        return {}
    by_cat: dict[str, list[int]] = {}
    for e in entries:
        by_cat.setdefault(e["category"], []).append(int(e["views"]))
    overall = sum(v for views in by_cat.values() for v in views) / max(
        1, sum(len(v) for v in by_cat.values())
    )
    if overall <= 0:
        return {}
    weights: dict[str, float] = {}
    for cat, views in by_cat.items():
        avg = sum(views) / len(views)
        weights[cat] = min(3.0, max(0.5, avg / overall))
    return weights


def winning_patterns() -> list[str]:
    """Human-readable report of category performance vs. the overall average."""
    entries = [e for e in _load() if e.get("category") and "views" in e]
    if not entries:
        return ["No performance data yet. Set YOUTUBE_API_KEY and run 'optimize'."]
    by_cat: dict[str, list[int]] = {}
    for e in entries:
        by_cat.setdefault(e["category"], []).append(int(e["views"]))
    overall = sum(v for views in by_cat.values() for v in views) / max(
        1, sum(len(v) for v in by_cat.values())
    )
    lines = []
    for cat, views in sorted(
        by_cat.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])
    ):
        avg = sum(views) / len(views)
        delta = (avg / overall - 1) * 100 if overall else 0.0
        lines.append(f"{cat}: avg {avg:.0f} views ({delta:+.0f}% vs channel avg, n={len(views)})")
    return lines


def long_form_candidates() -> list[dict[str, Any]]:
    """Shorts whose view counts qualify them for long-form expansion (Phase 9)."""
    out = []
    for e in _load():
        views = int(e.get("views", 0))
        for threshold, target in LONG_FORM_TIERS:
            if views >= threshold:
                out.append(
                    {
                        "topic": e.get("topic"),
                        "video_id": e.get("video_id"),
                        "views": views,
                        "recommended": target,
                    }
                )
                break
    return sorted(out, key=lambda x: -x["views"])
