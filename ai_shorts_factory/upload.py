"""Upload finished Shorts to YouTube via the Data API v3."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import settings
from .models import VideoProject

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _load_credentials():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_file = Path(settings.youtube_token_file)
    client_file = Path(settings.youtube_client_secret_file)
    creds = None

    # 1. CI / headless: build creds from a stored refresh token.
    if settings.youtube_refresh_token and client_file.exists():
        info = json.loads(client_file.read_text(encoding="utf-8"))
        data = info.get("installed") or info.get("web") or {}
        creds = Credentials(
            token=None,
            refresh_token=settings.youtube_refresh_token,
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return creds

    # 2. Reuse a previously saved token.
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json(), encoding="utf-8")
        return creds

    # 3. First-time interactive consent.
    if not client_file.exists():
        raise RuntimeError(
            f"Missing OAuth client secret file '{client_file}'. Download it from "
            "Google Cloud Console (OAuth client, type Desktop) and set "
            "YOUTUBE_CLIENT_SECRET_FILE."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    creds = flow.run_local_server(port=0)
    token_file.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload_video(project: VideoProject) -> str:
    """Upload the project's rendered video. Returns the new video id."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    if not project.video_path or not Path(project.video_path).exists():
        raise ValueError("project has no rendered video to upload.")
    if not project.metadata:
        raise ValueError("project has no metadata.")

    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": project.metadata.title,
            "description": project.metadata.description,
            "tags": project.metadata.tags,
            "categoryId": settings.youtube_category_id,
        },
        "status": {
            "privacyStatus": settings.youtube_privacy_status,
            "selfDeclaredMadeForKids": settings.youtube_made_for_kids,
        },
    }
    media_body = MediaFileUpload(
        str(project.video_path), chunksize=-1, resumable=True, mimetype="video/mp4"
    )
    request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media_body
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Upload progress: %d%%", int(status.progress() * 100))
    video_id = response["id"]
    logger.info("Uploaded: https://youtu.be/%s", video_id)

    # Post and pin an engagement comment to boost algorithmic signals.
    _post_pinned_comment(youtube, video_id, project.topic)

    return video_id


# Engagement comment templates — rotated randomly to feel organic.
_COMMENT_TEMPLATES = [
    "Would you survive this? Drop your answer below 👇",
    "What would you do in this situation? Tell me 👇",
    "How long do you think you'd last? Comment below 👇",
    "This still keeps me up at night. What's YOUR theory? 👇",
    "Scientists are divided on this. What do YOU think? 👇",
    "Rate how terrifying this is: 1-10 👇",
    "Could humanity actually survive this? Your thoughts 👇",
    "What fact here shocked you the most? Let me know 👇",
    "I bet you didn't know this before watching. What surprised you? 👇",
    "Tag someone who NEEDS to see this 👇",
    "Save this before it disappears from your feed 🔖",
    "Which fact blew your mind the most? 1, 2, or 3? 👇",
]


def _post_pinned_comment(youtube, video_id: str, topic: str) -> None:
    """Post a pinned comment on the video to encourage engagement."""
    import random

    comment_text = random.choice(_COMMENT_TEMPLATES)
    try:
        result = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": comment_text}
                    },
                }
            },
        ).execute()
        comment_id = result["snippet"]["topLevelComment"]["id"]
        # Pin the comment so it stays at the top.
        youtube.comments().setModerationStatus(
            id=comment_id, moderationStatus="published"
        ).execute()
        logger.info("Pinned comment posted on %s", video_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not post pinned comment: %s", exc)
