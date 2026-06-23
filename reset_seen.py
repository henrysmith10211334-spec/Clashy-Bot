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

Run this WHILE bot.py is stopped, then start bot.py again (with
CHECK_INTERVAL_MINUTES=1 if you want a fast test loop).
"""

import json
import os
import sys

SEEN_FILE = "seen_videos.json"


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


def main():
    seen = load_seen()

    if len(sys.argv) == 1:
        print(f"Currently marked as seen ({len(seen)} videos):")
        for vid in seen:
            print(f"  - {vid}  (https://www.youtube.com/watch?v={vid})")
        print("\nRun 'python reset_seen.py VIDEO_ID' to forget one, "
              "or 'python reset_seen.py --all' to forget all.")
        return

    arg = sys.argv[1]

    if arg == "--all":
        save_seen(set())
        print(f"Cleared all {len(seen)} seen video(s). "
              "Bot will treat them all as new on next check!")
    else:
        if arg in seen:
            seen.discard(arg)
            save_seen(seen)
            print(f"Forgot video {arg}. Bot will re-announce it on next check.")
        else:
            print(f"Video {arg} wasn't in the seen list. Nothing changed.")


if __name__ == "__main__":
    main()
