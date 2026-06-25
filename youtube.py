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
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")

CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "15"))
LIVE_CHECK_INTERVAL_MINUTES = int(os.environ.get("LIVE_CHECK_INTERVAL_MINUTES", "2"))
RESUBSCRIBE_INTERVAL_HOURS = int(os.environ.get("RESUBSCRIBE_INTERVAL_HOURS", "96"))

PING_MESSAGE = "-------- @here --------"

CREATOR_NAME = os.environ.get("CREATOR_NAME", "Clashy VR")
EMBED_COLOR = discord.Color(0xDDA731)
FOOTER_TEXT = "Youtube System • Clashy's Bot"

SEEN_FILE = "seen_videos.json"
LIVE_STATE_FILE = "live_state.json"

FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
LIVE_URL = f"https://www.youtube.com/channel/{YOUTUBE_CHANNEL_ID}/live"
HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
TOPIC_URL = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
WEBHOOK_PATH = "/webhook"


def load_seen() -> set[str]:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set[str]) -> None:
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


seen_videos: set[str] = load_seen()


def load_live_state() -> dict:
    if os.path.exists(LIVE_STATE_FILE):
        with open(LIVE_STATE_FILE, "r") as f:
            return json.load(f)
    return {"is_live": False, "video_id": None}


def save_live_state(state: dict) -> None:
    with open(LIVE_STATE_FILE, "w") as f:
        json.dump(state, f)


live_state: dict = load_live_state()


def extract_video_id(url: str) -> str | None:
    match = re.search(r"(?:v=|/)([\w-]{11})(?:&|$)", url)
    return match.group(1) if match else None


THUMBNAIL_CANDIDATES = [
    "maxresdefault.jpg",
    "sddefault.jpg",
    "hqdefault.jpg",
    "mqdefault.jpg",
    "default.jpg",
]
THUMBNAIL_RETRY_ATTEMPTS = 4
THUMBNAIL_RETRY_DELAY_SECONDS = 4


async def resolve_thumbnail_url(video_id: str) -> str:
    async with aiohttp.ClientSession() as session:
        for attempt in range(THUMBNAIL_RETRY_ATTEMPTS):
            for filename in THUMBNAIL_CANDIDATES:
                url = f"https://i.ytimg.com/vi/{video_id}/{filename}"
                try:
                    async with session.head(
                        url, timeout=aiohttp.ClientTimeout(total=3)
                    ) as resp:
                        if resp.status == 200:
                            return url
                except Exception:
                    continue

            if attempt < THUMBNAIL_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(THUMBNAIL_RETRY_DELAY_SECONDS)

    # Fallback if nothing was reachable
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def build_callback_url() -> str:
    parsed = urlparse(PUBLIC_URL)
    netloc = parsed.netloc
    if ":" not in netloc:
        default_port = 443 if parsed.scheme == "https" else 80
        netloc = f"{netloc}:{default_port}"
    fixed = urlunparse(parsed._replace(netloc=netloc))
    return f"{fixed}{WEBHOOK_PATH}"


async def subscribe_to_hub() -> None:
    callback_url = build_callback_url()
    data = {
        "hub.mode": "subscribe",
        "hub.topic": TOPIC_URL,
        "hub.callback": callback_url,
        "hub.lease_seconds": "432000",
        "hub.verify": "async",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(HUB_URL, data=data) as resp:
                if resp.status in (202, 204):
                    print(
                        f"WebSub: subscription request accepted (callback: {callback_url})"
                    )
                else:
                    text = await resp.text()
                    print(
                        f"WebSub: subscription request failed ({resp.status}): {text}"
                    )
    except Exception as e:
        print(f"WebSub: subscription request error: {e}")


async def fetch_live_video() -> tuple[str | None, str | None]:
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
    title = (
        title_match.group(1).replace(" - YouTube", "")
        if title_match
        else "Live Stream"
    )
    return video_id, title


def setup_youtube(bot: discord.Client):
    async def announce_new_video(entry) -> bool:
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            print(
                "Could not find Discord channel — check DISCORD_CHANNEL_ID and bot permissions."
            )
            return False

        video_url = entry.link
        video_id = entry.get("yt_videoid") or extract_video_id(video_url)
        thumbnail_url = await resolve_thumbnail_url(video_id) if video_id else None

        embed = discord.Embed(
            description=(
                f"**{CREATOR_NAME}** has posted a new video\n\n"
                f"[Jump to Clashy's new video!]({video_url})"
            ),
            color=EMBED_COLOR,
        )
        if thumbnail_url:
            embed.set_image(url=thumbnail_url)
        embed.set_footer(text=FOOTER_TEXT)

        await channel.send(embed=embed)
        await channel.send(content=PING_MESSAGE)
        return True

    @tasks.loop(hours=RESUBSCRIBE_INTERVAL_HOURS)
    async def resubscribe_loop():
        await subscribe_to_hub()

    async def handle_webhook_get(request: web.Request) -> web.Response:
        challenge = request.query.get("hub.challenge", "")
        mode = request.query.get("hub.mode", "")
        print(f"WebSub: verification GET received (mode={mode})")
        return web.Response(text=challenge, status=200)

    async def handle_webhook_post(request: web.Request) -> web.Response:
        body = await request.text()
        feed = feedparser.parse(body)

        for entry in feed.entries:
            video_id = entry.get("yt_videoid")
            if not video_id or video_id in seen_videos:
                continue

            posted = await announce_new_video(entry)
            if posted:
                seen_videos.add(video_id)

        save_seen(seen_videos)
        return web.Response(status=204)

    @tasks.loop(minutes=LIVE_CHECK_INTERVAL_MINUTES)
    async def check_for_live_stream():
        global live_state

        try:
            video_id, title = await fetch_live_video()
        except Exception as e:
            print(f"Live check failed: {e}")
            return

        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            print(
                "Could not find Discord channel — check DISCORD_CHANNEL_ID and bot permissions."
            )
            return

        currently_live = video_id is not None

        if currently_live and not live_state["is_live"]:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            embed = discord.Embed(
                description=(
                    f"**{CREATOR_NAME}** is now live\n\n"
                    f"[Jump to Clashy's live stream!]({video_url})"
                ),
                color=discord.Color.from_rgb(255, 0, 0),
            )
            embed.set_image(url=await resolve_thumbnail_url(video_id))
            embed.set_footer(text=FOOTER_TEXT)

            await channel.send(embed=embed)
            await channel.send(content=PING_MESSAGE)

            live_state = {"is_live": True, "video_id": video_id}
            save_live_state(live_state)

            seen_videos.add(video_id)
            save_seen(seen_videos)

        elif not currently_live and live_state["is_live"]:
            live_state = {"is_live": False, "video_id": None}
            save_live_state(live_state)

    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def check_for_new_video():
        feed = feedparser.parse(FEED_URL)
        if not feed.entries:
            return

        is_first_run = len(seen_videos) == 0
        new_entries = [e for e in feed.entries if e.yt_videoid not in seen_videos]

        if is_first_run:
            for entry in feed.entries:
                seen_videos.add(entry.yt_videoid)
            save_seen(seen_videos)
            print("First run: caching existing videos, no announcement posted.")
            return

        for entry in reversed(new_entries):
            posted = await announce_new_video(entry)
            if posted:
                seen_videos.add(entry.yt_videoid)

        if new_entries:
            save_seen(seen_videos)

    def start_tasks() -> None:
        if not check_for_new_video.is_running():
            check_for_new_video.start()
        if not check_for_live_stream.is_running():
            check_for_live_stream.start()
        if not resubscribe_loop.is_running():
            resubscribe_loop.start()

    def build_web_app() -> web.Application:
        app = web.Application()
        app.router.add_get(WEBHOOK_PATH, handle_webhook_get)
        app.router.add_post(WEBHOOK_PATH, handle_webhook_post)
        return app

    # Manual trigger used by /check-now
    async def manual_check_for_new_video() -> bool:
        await check_for_new_video()
        return True

    return start_tasks, build_web_app, manual_check_for_new_video
