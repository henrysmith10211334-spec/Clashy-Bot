"""
reset_seen.py — Removes one or all video IDs from seen_videos.json so the
bot will treat them as "new" again on its next check. Lets you re-trigger
a test announcement without uploading a real new video every time.

Usage:
    python reset_seen.py                  -> lists what's currently marked as seen
    python reset_seen.py VIDEO_ID         -> forgets one specific video ID
    python reset_seen.py --all            -> forgets ALL seen videos (bot will
                                              re-announce every existing video
                                              on the channel next check!)

This version ALSO notifies the running bot so you do NOT need to restart it.
"""

import json
import os
import sys
import asyncio
import aiohttp

SEEN_FILE = "seen_videos.json"

# PUBLIC_URL must match the bot's PUBLIC_URL environment variable
BOT_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


async def notify_bot(video_id):
    """Tell the running bot to clear the in-memory seen cache."""
    if not BOT_URL:
        print("PUBLIC_URL not set — cannot notify running bot.")
        return

    url = f"{BOT_URL}/clear-seen"
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, json={"video_id": video_id})
            print("Notified running bot to clear in-memory cache.")
        except Exception as e:
            print(f"Failed to notify bot: {e}")


def main():
    seen = load_seen()

    # No args → list seen videos
    if len(sys.argv) == 1:
        print(f"Currently marked as seen ({len(seen)} videos):")
        for vid in seen:
            print(f"  - {vid}  (https://www.youtube.com/watch?v={vid})")
        print("\nRun 'python reset_seen.py VIDEO_ID' to forget one, "
              "or 'python reset_seen.py --all' to forget all.")
        return

    arg = sys.argv[1]

    # Clear ALL
    if arg == "--all":
        save_seen(set())
        print(f"Cleared all {len(seen)} seen video(s).")
        asyncio.run(notify_bot(None))
        return

    # Clear ONE
    if arg in seen:
        seen.discard(arg)
        save_seen(seen)
        print(f"Forgot video {arg}.")
        asyncio.run(notify_bot(arg))
    else:
        print(f"Video {arg} wasn't in the seen list. Nothing changed.")


if __name__ == "__main__":
    main()
