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

# YouTube Analytics data lags 24-72h behind real time. Learning functions only
# analyse videos uploaded at least this many days ago so decisions are never
# based on partial metrics of freshly uploaded videos.
STATS_MATURITY_DAYS = 3

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
    """Attach the uploaded video id + upload time to the latest entry for *topic*."""
    now = dt.datetime.now()
    entries = _load()
    for entry in reversed(entries):
        if entry.get("topic") == topic and not entry.get("video_id"):
            entry["video_id"] = video_id
            entry["uploaded_at"] = now.isoformat(timespec="seconds")
            entry["upload_hour"] = now.hour
            break
    else:
        entries.append(
            {
                "topic": topic,
                "video_id": video_id,
                "uploaded_at": now.isoformat(timespec="seconds"),
                "upload_hour": now.hour,
                "created_at": now.isoformat(timespec="seconds"),
            }
        )
    _save(entries)


def record_detail(topic: str, **fields: Any) -> None:
    """Attach extra details (hook, duration_seconds, ...) to the latest entry."""
    entries = _load()
    for entry in reversed(entries):
        if entry.get("topic") == topic:
            entry.update({k: v for k, v in fields.items() if v is not None})
            _save(entries)
            return


def refresh_stats() -> list[dict[str, Any]]:
    """Refresh statistics for all recorded videos.

    Prefers the YouTube Analytics API (retention, watch time, subscribers
    gained — needs the yt-analytics.readonly OAuth scope); falls back to
    public Data API stats via YOUTUBE_API_KEY for views/likes/comments.
    """
    entries = _load()
    ids = [e["video_id"] for e in entries if e.get("video_id")]
    if not ids:
        return entries

    now = dt.datetime.now().isoformat(timespec="seconds")

    from .analytics import fetch_video_analytics

    analytics = fetch_video_analytics(ids)
    if analytics:
        for entry in entries:
            m = analytics.get(entry.get("video_id", ""))
            if not m:
                continue
            entry.update(m)
            entry["stats_updated_at"] = now
        _save(entries)
        return entries

    if not settings.youtube_api_key:
        logger.info("No Analytics access and no YOUTUBE_API_KEY; skipping refresh.")
        return entries

    from googleapiclient.discovery import build

    stats: dict[str, dict[str, Any]] = {}
    try:
        youtube = build("youtube", "v3", developerKey=settings.youtube_api_key)
        for i in range(0, len(ids), 50):
            response = (
                youtube.videos()
                .list(part="statistics", id=",".join(ids[i : i + 50]))
                .execute()
            )
            for item in response.get("items", []):
                stats[item["id"]] = item.get("statistics", {})
    except Exception as exc:
        logger.warning("Data API stats refresh failed: %s", exc)
        return entries

    for entry in entries:
        s = stats.get(entry.get("video_id", ""))
        if not s:
            continue
        for field_name, api_key in (
            ("views", "viewCount"),
            ("likes", "likeCount"),
            ("comments", "commentCount"),
        ):
            if _valid_number(s.get(api_key)):
                entry[field_name] = int(float(s[api_key]))
        entry["stats_updated_at"] = now
    _save(entries)
    return entries


def _entry_score(e: dict[str, Any]) -> float:
    """Composite performance score used for automatic strategy adjustment.

    views weighted by retention quality and subscriber conversion when
    Analytics data is available; plain views otherwise.
    """
    views = float(e["views"]) if _valid_number(e.get("views")) else 0.0
    score = views
    retention = e.get("retention_pct")
    if _valid_number(retention):
        # 80% retention doubles a view's value; 40% keeps it at 1x; floor 0.25x.
        score *= max(0.25, float(retention) / 40.0)
    subs = e.get("subs_gained")
    if _valid_number(subs) and views > 0:
        # Reward subscriber conversion: +10% per sub/1k views, capped at 2x.
        score *= min(2.0, 1.0 + (float(subs) / views) * 100.0)
    return score


def category_weights() -> dict[str, float]:
    """Return {category: weight} learned from past performance.

    Weight = category's average composite score (views x retention x subs
    conversion) relative to the overall average, clamped to [0.3, 4.0] so no
    category is ever fully starved and winners are boosted up to 4x.
    """
    entries = [
        e
        for e in _load()
        if e.get("category") and _valid_number(e.get("views")) and _is_mature(e)
    ]
    if len(entries) < 5:  # not enough signal yet
        return {}
    by_cat: dict[str, list[float]] = {}
    for e in entries:
        by_cat.setdefault(e["category"], []).append(_entry_score(e))
    overall = sum(v for scores in by_cat.values() for v in scores) / max(
        1, sum(len(v) for v in by_cat.values())
    )
    if overall <= 0:
        return {}
    weights: dict[str, float] = {}
    for cat, scores in by_cat.items():
        avg = sum(scores) / len(scores)
        weights[cat] = min(4.0, max(0.3, avg / overall))
    return weights


# Injected into the topic/hook/script prompts when the latest measurable video
# failed to hold the audience.
RETENTION_FEEDBACK_THRESHOLD = 80.0
SWIPE_AWAY_THRESHOLD = 50.0
_URGENT_HOOK_FEEDBACK = (
    "[URGENT_HOOK_OPTIMIZATION] Over half of viewers swiped away within the "
    "first seconds of the previous video. Make the hook 2x more dramatic: a "
    "shocking, high-stakes statement in the first 3 words, and the single most "
    "jaw-dropping visual of the whole video in the very first frame."
)
_RETENTION_FEEDBACK = (
    "[OPTIMIZATION] The previous video failed to hold the audience "
    "(retention below 80%). Make the opening hook shorter and more dramatic, "
    "and increase the visual pace: every scene's image must change subject, "
    "scale or palette more aggressively."
)


def retention_feedback() -> str:
    """Return an LLM prompt addendum when the latest measured video underperformed.

    Looks at the most recently uploaded video that is mature enough
    (>= STATS_MATURITY_DAYS old) to have complete Analytics data. Returns an
    empty string when retention was fine or no data is available.
    """
    entries = [
        e
        for e in _with_stats()
        if _valid_number(e.get("retention_pct"))
    ]
    if not entries:
        return ""
    latest = max(entries, key=lambda e: str(e.get("uploaded_at", "")))
    swipe = latest.get("swipe_away_pct")
    if _valid_number(swipe) and float(swipe) > SWIPE_AWAY_THRESHOLD:
        return _URGENT_HOOK_FEEDBACK
    if float(latest["retention_pct"]) < RETENTION_FEEDBACK_THRESHOLD:
        return _RETENTION_FEEDBACK
    return ""


def winning_patterns() -> list[str]:
    """Human-readable report of category performance vs. the overall average."""
    entries = [e for e in _load() if e.get("category") and "views" in e]
    if not entries:
        return ["No performance data yet. Run 'optimize' after videos have stats."]
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_cat.setdefault(e["category"], []).append(e)
    overall = sum(_entry_score(e) for e in entries) / len(entries)
    lines = []
    for cat, items in sorted(
        by_cat.items(),
        key=lambda kv: -sum(_entry_score(e) for e in kv[1]) / len(kv[1]),
    ):
        avg_score = sum(_entry_score(e) for e in items) / len(items)
        avg_views = sum(int(e.get("views", 0)) for e in items) / len(items)
        delta = (avg_score / overall - 1) * 100 if overall else 0.0
        lines.append(
            f"{cat}: avg {avg_views:.0f} views, score {delta:+.0f}% vs channel avg "
            f"(n={len(items)})"
        )
    return lines


def _is_mature(e: dict[str, Any]) -> bool:
    """True when the entry's video is old enough for its Analytics data to be complete."""
    uploaded = e.get("uploaded_at")
    if not uploaded:
        return False
    try:
        uploaded_dt = dt.datetime.fromisoformat(str(uploaded))
    except ValueError:
        return False
    return dt.datetime.now() - uploaded_dt >= dt.timedelta(days=STATS_MATURITY_DAYS)


def _valid_number(v: Any) -> bool:
    """True for a real, finite number (rejects None, NaN, inf, non-numeric)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return f == f and f not in (float("inf"), float("-inf"))


def _with_stats() -> list[dict[str, Any]]:
    return [
        e
        for e in _load()
        if _valid_number(e.get("views")) and _is_mature(e)
    ]


def _leaders(key: str, label: str, fmt: str = "{:.1f}") -> list[str]:
    entries = [e for e in _with_stats() if e.get(key) is not None]
    lines = []
    for e in sorted(entries, key=lambda x: -float(x.get(key, 0)))[:5]:
        value = fmt.format(float(e.get(key, 0)))
        lines.append(f"{value} {label}  {e.get('topic', '?')}")
    return lines


def retention_leaders() -> list[str]:
    """Videos ranked by audience retention (averageViewPercentage)."""
    return _leaders("retention_pct", "% retention", "{:.0f}")


def watch_time_leaders() -> list[str]:
    """Videos ranked by total watch time."""
    return _leaders("watch_minutes", "min watched", "{:.0f}")


def subscriber_leaders() -> list[str]:
    """Videos ranked by subscriber conversion (subs gained per 1k views)."""
    entries = [
        e
        for e in _with_stats()
        if e.get("subs_gained") is not None and int(e.get("views", 0)) > 0
    ]
    lines = []
    for e in sorted(
        entries, key=lambda x: -float(x["subs_gained"]) / float(x["views"])
    )[:5]:
        rate = float(e["subs_gained"]) / float(e["views"]) * 1000
        lines.append(
            f"{rate:.1f} subs/1k views ({e['subs_gained']} total)  {e.get('topic', '?')}"
        )
    return lines


def top_topics() -> list[str]:
    """Videos ranked by composite performance score."""
    entries = _with_stats()
    lines = []
    for e in sorted(entries, key=lambda x: -_entry_score(x))[:5]:
        lines.append(f"{int(e.get('views', 0))} views  {e.get('topic', '?')}")
    return lines


def top_hooks() -> list[str]:
    """Hooks of the best-performing videos (pattern source for future scripts)."""
    entries = [e for e in _with_stats() if e.get("hook")]
    lines = []
    for e in sorted(entries, key=lambda x: -_entry_score(x))[:5]:
        retention = e.get("retention_pct")
        suffix = f" ({retention:.0f}% retention)" if retention is not None else ""
        lines.append(f'"{e["hook"]}"{suffix}')
    return lines


def best_upload_hours() -> list[str]:
    """Upload hours ranked by average composite score."""
    entries = [e for e in _with_stats() if e.get("upload_hour") is not None]
    by_hour: dict[int, list[float]] = {}
    for e in entries:
        by_hour.setdefault(int(e["upload_hour"]), []).append(_entry_score(e))
    lines = []
    for hour, scores in sorted(
        by_hour.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])
    )[:5]:
        lines.append(f"{hour:02d}:00 UTC  avg score {sum(scores) / len(scores):.0f} (n={len(scores)})")
    return lines


_DURATION_BUCKETS = [(0, 20, "<20s"), (20, 26, "20-25s"), (26, 31, "26-30s"), (31, 999, "31s+")]


def best_durations() -> list[str]:
    """Video-length buckets ranked by average composite score."""
    entries = [e for e in _with_stats() if e.get("duration_seconds")]
    by_bucket: dict[str, list[float]] = {}
    for e in entries:
        d = float(e["duration_seconds"])
        for lo, hi, label in _DURATION_BUCKETS:
            if lo <= d < hi:
                by_bucket.setdefault(label, []).append(_entry_score(e))
                break
    lines = []
    for label, scores in sorted(
        by_bucket.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])
    ):
        lines.append(f"{label}  avg score {sum(scores) / len(scores):.0f} (n={len(scores)})")
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
