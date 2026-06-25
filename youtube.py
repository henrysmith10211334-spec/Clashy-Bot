import os
import json
import re
import asyncio

import discord
import feedparser
import aiohttp
from aiohttp import web
from discord.ext import tasks
from urllib.parse import urlparse, urlunparse

# Environment configuration
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")

CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "15"))
LIVE_CHECK_INTERVAL_MINUTES = int(os.environ.get("LIVE_CHECK_INTERVAL_MINUTES", "2"))
RESUBSCRIBE_INTERVAL_HOURS = int(os.environ.get("RESUBSCRIBE_INTERVAL_HOURS", "96"))

CREATOR_NAME = os.environ.get("CREATOR_NAME", "Clashy VR")
EMBED_COLOR = discord.Color(0xDDA731)
FOOTER_TEXT = "Youtube System • Clashy's Bot"
PING_MESSAGE = "-------- @here --------"

SEEN_FILE = "seen_videos.json"
LIVE_STATE_FILE = "live_state.json"

FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
LIVE_URL = f"https://www.youtube.com/channel/{YOUTUBE_CHANNEL_ID}/live"
TOPIC_URL = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
WEBHOOK_PATH = "/webhook"


# -----------------------------
# Seen video tracking
# -----------------------------
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


seen_videos = load_seen()


# -----------------------------
# Live state tracking
# -----------------------------
def load_live_state():
    if os.path.exists(LIVE_STATE_FILE):
        with open(LIVE_STATE_FILE, "r") as f:
            return json.load(f)
    return {"is_live": False, "video_id": None}


def save_live_state(state):
    with open(LIVE_STATE_FILE, "w") as f:
        json.dump(state, f)


live_state = load_live_state()


# -----------------------------
# Thumbnail resolution
# -----------------------------
THUMBNAIL_ORDER = [
    "maxresdefault.jpg",
    "sddefault.jpg",
    "hqdefault.jpg",
    "mqdefault.jpg",
    "default.jpg",
]


async def resolve_thumbnail(video_id):
    async with aiohttp.ClientSession() as session:
        for filename in THUMBNAIL_ORDER:
            url = f"https://i.ytimg.com/vi/{video_id}/{filename}"
            try:
                async with session.head(url) as resp:
                    if resp.status == 200:
                        return url
            except:
                pass
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


# -----------------------------
# WebSub callback URL
# -----------------------------
def build_callback_url():
    parsed = urlparse(PUBLIC_URL)
    netloc = parsed.netloc
    if ":" not in netloc:
        default_port = 443 if parsed.scheme == "https" else 80
        netloc = f"{netloc}:{default_port}"
    fixed = urlunparse(parsed._replace(netloc=netloc))
    return f"{fixed}{WEBHOOK_PATH}"


# -----------------------------
# WebSub subscription
# -----------------------------
async def subscribe_to_hub():
    callback = build_callback_url()
    data = {
        "hub.mode": "subscribe",
        "hub.topic": TOPIC_URL,
        "hub.callback": callback,
        "hub.lease_seconds": "432000",
        "hub.verify": "async",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(HUB_URL, data=data) as resp:
                if resp.status in (202, 204):
                    print("WebSub subscription accepted.")
                else:
                    print(f"WebSub subscription failed: {resp.status}")
    except Exception as e:
        print(f"WebSub subscription error: {e}")


# -----------------------------
# Live detection
# -----------------------------
async def fetch_live_video():
    async with aiohttp.ClientSession() as session:
        async with session.get(LIVE_URL, allow_redirects=True) as resp:
            final_url = str(resp.url)
            html = await resp.text()

    match = re.search(r"watch\?v=([\w-]{11})", final_url)
    if not match:
        return None, None

    video_id = match.group(1)
    if '"isLiveNow":true' not in html and '"isLive":true' not in html:
        return None, None

    title_match = re.search(r"<title>(.*?)</title>", html)
    title = title_match.group(1).replace(" - YouTube", "") if title_match else "Live Stream"

    return video_id, title


# -----------------------------
# Main setup function
# -----------------------------
def setup_youtube(bot):

    # -------------------------
    # Announce new upload
    # -------------------------
    async def announce_upload(entry):
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            print("Discord channel not found.")
            return False

        video_url = entry.link
        video_id = entry.get("yt_videoid")
        thumb = await resolve_thumbnail(video_id)

        embed = discord.Embed(
            description=f"**{CREATOR_NAME}** has posted a new video\n\n[Jump to Clashy's new video!]({video_url})",
            color=EMBED_COLOR,
        )
        embed.set_image(url=thumb)
        embed.set_footer(text=FOOTER_TEXT)

        await channel.send(embed=embed)
        await channel.send(PING_MESSAGE)
        return True

    # -------------------------
    # Poll for new uploads
    # -------------------------
    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def poll_uploads():
        feed = feedparser.parse(FEED_URL)
        if not feed.entries:
            return

        first_run = len(seen_videos) == 0
        new_items = [e for e in feed.entries if e.yt_videoid not in seen_videos]

        if first_run:
            for e in feed.entries:
                seen_videos.add(e.yt_videoid)
            save_seen(seen_videos)
            print("Initial run: caching existing uploads.")
            return

        for entry in reversed(new_items):
            if await announce_upload(entry):
                seen_videos.add(entry.yt_videoid)

        if new_items:
            save_seen(seen_videos)

    # -------------------------
    # Poll for live streams
    # -------------------------
    @tasks.loop(minutes=LIVE_CHECK_INTERVAL_MINUTES)
    async def poll_live():
        global live_state

        try:
            video_id, title = await fetch_live_video()
        except Exception as e:
            print(f"Live check error: {e}")
            return

        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            return

        is_live = video_id is not None

        if is_live and not live_state["is_live"]:
            url = f"https://www.youtube.com/watch?v={video_id}"
            embed = discord.Embed(
                description=f"**{CREATOR_NAME}** is now live\n\n[Jump to Clashy's live stream!]({url})",
                color=discord.Color.from_rgb(255, 0, 0),
            )
            embed.set_image(url=await resolve_thumbnail(video_id))
            embed.set_footer(text=FOOTER_TEXT)

            await channel.send(embed=embed)
            await channel.send(PING_MESSAGE)

            live_state = {"is_live": True, "video_id": video_id}
            save_live_state(live_state)

            seen_videos.add(video_id)
            save_seen(seen_videos)

        elif not is_live and live_state["is_live"]:
            live_state = {"is_live": False, "video_id": None}
            save_live_state(live_state)

    # -------------------------
    # WebSub handlers
    # -------------------------
    async def handle_get(request):
        return web.Response(text=request.query.get("hub.challenge", ""))

    async def handle_post(request):
        body = await request.text()
        feed = feedparser.parse(body)

        for entry in feed.entries:
            vid = entry.get("yt_videoid")
            if vid and vid not in seen_videos:
                if await announce_upload(entry):
                    seen_videos.add(vid)

        save_seen(seen_videos)
        return web.Response(status=204)

    # -------------------------
    # Clear seen cache (for reset_seen.py)
    # -------------------------
    async def clear_seen(video_id):
        if video_id is None:
            seen_videos.clear()
        else:
            seen_videos.discard(video_id)
        save_seen(seen_videos)
        return True

    async def handle_clear_seen(request):
        data = await request.json()
        vid = data.get("video_id")
        await clear_seen(vid)
        return web.Response(text="OK")

    # -------------------------
    # Build aiohttp app
    # -------------------------
    def build_app():
        app = web.Application()
        app.router.add_get(WEBHOOK_PATH, handle_get)
        app.router.add_post(WEBHOOK_PATH, handle_post)
        app.router.add_post("/clear-seen", handle_clear_seen)
        return app

    # -------------------------
    # Manual check for /check-now
    # -------------------------
    async def manual_check():
        await poll_uploads()
        return True

    # -------------------------
    # Start background tasks
    # -------------------------
    def start_tasks():
        if not poll_uploads.is_running():
            poll_uploads.start()
        if not poll_live.is_running():
            poll_live.start()

    return start_tasks, build_app, manual_check
