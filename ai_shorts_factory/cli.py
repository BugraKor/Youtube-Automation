"""Command-line interface for AI Shorts Factory."""

from __future__ import annotations

import argparse
import logging
import sys


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _cmd_generate(args: argparse.Namespace) -> int:
    from .pipeline import create_short

    project = create_short(topic=args.topic)
    print(f"\nVideo: {project.video_path}")
    if project.metadata:
        print(f"Title: {project.metadata.title}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import create_short
    from .upload import upload_video

    project = create_short(topic=args.topic)
    print(f"\nVideo: {project.video_path}")
    video_id = upload_video(project)
    print(f"Uploaded: https://youtu.be/{video_id}")
    return 0


def _cmd_upload(args: argparse.Namespace) -> int:
    """Upload an already-rendered video folder (must contain final.mp4 + metadata.json)."""
    import json
    from pathlib import Path

    from .models import VideoMetadata, VideoProject
    from .upload import upload_video

    folder = Path(args.folder)
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    project = VideoProject(
        topic=meta.get("topic", ""),
        workdir=folder,
        video_path=folder / "final.mp4",
        metadata=VideoMetadata(
            title=meta["title"], description=meta["description"], tags=meta["tags"]
        ),
    )
    video_id = upload_video(project)
    print(f"Uploaded: https://youtu.be/{video_id}")
    return 0


def _cmd_auth(args: argparse.Namespace) -> int:
    """Run the one-time OAuth flow and print the refresh token for CI."""
    from .upload import _load_credentials

    creds = _load_credentials()
    print("\nAuthorisation successful. Token saved.")
    if creds.refresh_token:
        print("\nStore this as the YOUTUBE_REFRESH_TOKEN secret for CI:\n")
        print(creds.refresh_token)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-shorts-factory",
        description="Automated 'What If' YouTube Shorts generator.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="generate a Short (no upload)")
    p_gen.add_argument("--topic", help="force a specific topic")
    p_gen.set_defaults(func=_cmd_generate)

    p_run = sub.add_parser("run", help="generate a Short and upload it")
    p_run.add_argument("--topic", help="force a specific topic")
    p_run.set_defaults(func=_cmd_run)

    p_up = sub.add_parser("upload", help="upload a previously generated output folder")
    p_up.add_argument("folder", help="path to an output/<timestamp> folder")
    p_up.set_defaults(func=_cmd_upload)

    p_auth = sub.add_parser("auth", help="run YouTube OAuth and print refresh token")
    p_auth.set_defaults(func=_cmd_auth)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001 - top-level CLI handler
        logging.getLogger("ai_shorts_factory").error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
