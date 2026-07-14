"""One-time channel metadata reset: lock the algorithm onto the cosmic niche.

Updates the channel description and keywords via ``youtube.channels().update``
(brandingSettings) so YouTube re-reads the channel as a space / astrophysics /
cosmic-dread channel after the topic-drift period.

Requires the full ``youtube`` OAuth scope (broader than the upload scope the
automation normally uses), so this script runs its own consent flow once:

    pip install google-auth-oauthlib google-api-python-client
    python scripts/update_channel_metadata.py

It expects ``client_secret.json`` in the repo root (same file the automation
uses). A browser window opens for consent; the token is NOT stored.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCOPES = ["https://www.googleapis.com/auth/youtube"]

CHANNEL_DESCRIPTION = (
    "Omnix explores the terrifying scale of the universe — black holes, dying "
    "stars, the Great Filter, cosmic silence and the ultimate scientific "
    "'What if's. Cinematic space and astrophysics Shorts engineered to make "
    "you feel very, very small.\n\n"
    "New cosmic dread Shorts every day. Subscribe if you dare to know how "
    "insignificant we really are.\n\n"
    "#space #astrophysics #cosmicdread #universe #blackholes #greatfilter "
    "#fermiparadox #shorts"
)

CHANNEL_KEYWORDS = (
    '"space" "astrophysics" "cosmic dread" "universe scale" "black holes" '
    '"great filter" "fermi paradox" "existential space facts" '
    '"what if space scenarios" "cosmic horror science" "dying stars" '
    '"observable universe" "space shorts" "science shorts"'
)


def generate_description_with_gemini() -> str:
    """Ask Gemini for an SEO-rich description; fall back to the hardcoded one."""
    try:
        from ai_shorts_factory.config import settings
        from ai_shorts_factory.llm import generate_text

        if not settings.gemini_api_key:
            return CHANNEL_DESCRIPTION
        prompt = (
            "Write a YouTube CHANNEL description (max 900 chars) for 'Omnix', "
            "a faceless Shorts channel locked to ONE niche: space, "
            "astrophysics and cosmic dread — the terrifying scale of the "
            "universe, black holes, the Great Filter, cosmic silence and "
            "ultimate scientific 'What if's.\n"
            "Requirements: the first 2 sentences must contain the main search "
            "keywords (space, astrophysics, cosmic dread, universe) naturally; "
            "dark cinematic tone; end with a subscribe line and 6-8 hashtags "
            "including #shorts. NEVER mention psychology, habits or fiction.\n"
            "Return ONLY the description text."
        )
        text = generate_text(prompt, temperature=0.7).strip()
        return text[:1000] if text else CHANNEL_DESCRIPTION
    except Exception as exc:  # noqa: BLE001 - metadata reset must not depend on Gemini
        print(f"Gemini unavailable ({exc}); using the built-in description.")
        return CHANNEL_DESCRIPTION


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    client_file = ROOT / "client_secret.json"
    if not client_file.exists():
        sys.exit("client_secret.json not found in the repo root.")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
    creds = flow.run_local_server(port=0)
    youtube = build("youtube", "v3", credentials=creds)

    channel = (
        youtube.channels().list(part="id,brandingSettings", mine=True).execute()
    )
    items = channel.get("items", [])
    if not items:
        sys.exit("No channel found for the authorized account.")
    item = items[0]

    branding = item.get("brandingSettings", {})
    branding.setdefault("channel", {})
    branding["channel"]["description"] = generate_description_with_gemini()
    branding["channel"]["keywords"] = CHANNEL_KEYWORDS

    youtube.channels().update(
        part="brandingSettings",
        body={"id": item["id"], "brandingSettings": branding},
    ).execute()
    print("Channel description and keywords updated — niche locked to cosmic dread.")


if __name__ == "__main__":
    main()
