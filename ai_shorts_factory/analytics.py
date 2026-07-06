"""YouTube Analytics API integration (OAuth2, read-only).

Fetches per-video retention, watch time and subscriber metrics that the plain
Data API cannot provide. Requires the refresh token to have been granted
``yt-analytics.readonly`` (re-run ``ai-shorts-factory auth`` once). All
functions fail soft: when the scope is missing or the API errors, they return
empty data so the rest of the pipeline keeps working on public stats alone.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Per-video metrics pulled from the Analytics API.
_METRICS = (
    "views,likes,comments,estimatedMinutesWatched,"
    "averageViewDuration,averageViewPercentage,subscribersGained"
)
_START_DATE = "2020-01-01"
_CHUNK = 200  # video filter limit safety margin


def fetch_video_analytics(video_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Return {video_id: metrics} from the YouTube Analytics API.

    Metrics keys: views, likes, comments, watch_minutes, avg_view_duration,
    retention_pct (averageViewPercentage), subs_gained.
    """
    if not video_ids:
        return {}
    try:
        from googleapiclient.discovery import build

        from .upload import ALL_SCOPES, _load_credentials

        creds = _load_credentials(ALL_SCOPES)
        analytics = build("youtubeAnalytics", "v2", credentials=creds)
    except Exception as exc:
        logger.warning(
            "YouTube Analytics unavailable (%s). Re-run 'ai-shorts-factory auth' "
            "to grant the yt-analytics.readonly scope.",
            exc,
        )
        return {}

    end_date = dt.date.today().isoformat()
    results: dict[str, dict[str, Any]] = {}
    for i in range(0, len(video_ids), _CHUNK):
        chunk = video_ids[i : i + _CHUNK]
        try:
            response = (
                analytics.reports()
                .query(
                    ids="channel==MINE",
                    startDate=_START_DATE,
                    endDate=end_date,
                    metrics=_METRICS,
                    dimensions="video",
                    filters="video==" + ",".join(chunk),
                    maxResults=len(chunk),
                )
                .execute()
            )
        except Exception as exc:
            logger.warning("Analytics query failed: %s", exc)
            return results
        headers = [h["name"] for h in response.get("columnHeaders", [])]
        for row in response.get("rows", []) or []:
            data = dict(zip(headers, row))
            vid = str(data.get("video", ""))
            if not vid:
                continue
            results[vid] = {
                "views": int(data.get("views", 0)),
                "likes": int(data.get("likes", 0)),
                "comments": int(data.get("comments", 0)),
                "watch_minutes": float(data.get("estimatedMinutesWatched", 0)),
                "avg_view_duration": float(data.get("averageViewDuration", 0)),
                "retention_pct": float(data.get("averageViewPercentage", 0)),
                "subs_gained": int(data.get("subscribersGained", 0)),
            }
    logger.info("Fetched Analytics metrics for %d/%d videos.", len(results), len(video_ids))
    return results
