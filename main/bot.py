import asyncio
import os
import json
import re
import discord
import feedparser
import aiohttp
from discord.ext import tasks

# ---- CONFIG (set these in Railway "Variables" tab, not here) ----
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "5"))
LIVE_CHECK_INTERVAL_MINUTES = int(os.environ.get("LIVE_CHECK_INTERVAL_MINUTES", "2"))

SEEN_FILE = "seen_videos.json"
LIVE_STATE_FILE = "live_state.json"
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
LIVE_URL = f"https://www.youtube.com/channel/{YOUTUBE_CHANNEL_ID}/live"

intents = discord.Intents.default()
client = discord.Client(intents=intents)


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen), f)


seen_videos = load_seen()


def load_live_state():
    if os.path.exists(LIVE_STATE_FILE):
        with open(LIVE_STATE_FILE, "r") as f:
            return json.load(f)
    return {"is_live": False, "video_id": None}


def save_live_state(state):
    with open(LIVE_STATE_FILE, "w") as f:
        json.dump(state, f)


live_state = load_live_state()


async def fetch_live_video():
    """
    Checks the channel's /live URL. If a stream is currently live, YouTube
    redirects to the watch page and we can pull the video ID + title.
    Returns (video_id, title) or (None, None) if nothing is live.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(LIVE_URL, allow_redirects=True) as resp:
            final_url = str(resp.url)
            html = await resp.text()

    match = re.search(r"watch\?v=([\w-]{11})", final_url)
    if not match:
        return None, None

    video_id = match.group(1)

    # Confirm it's actually live right now (not just a normal video the
    # /live URL happened to land on) by checking for the live badge in HTML
    if '"isLiveNow":true' not in html and '"isLive":true' not in html:
        return None, None

    title_match = re.search(r'<title>(.*?)</title>', html)
    title = title_match.group(1).replace(" - YouTube", "") if title_match else "Live Stream"

    return video_id, title


@tasks.loop(minutes=LIVE_CHECK_INTERVAL_MINUTES)
async def check_for_live_stream():
    global live_state
    try:
        video_id, title = await fetch_live_video()
    except Exception as e:
        print(f"Live check failed: {e}")
        return

    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print("Could not find Discord channel — check DISCORD_CHANNEL_ID and bot permissions.")
        return

    currently_live = video_id is not None

    if currently_live and not live_state["is_live"]:
        # Just went live
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        embed = discord.Embed(
            title=title,
            url=video_url,
            description="🔴 **LIVE NOW**",
            color=discord.Color.from_rgb(255, 0, 0),
        )
        embed.set_image(url=f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg")

        await channel.send(content=f"🔴 **Going live right now!** {video_url}", embed=embed)

        live_state = {"is_live": True, "video_id": video_id}
        save_live_state(live_state)
        # Mark this video id as seen so the normal upload-check doesn't
        # also announce it later as a regular "new video"
        seen_videos.add(video_id)
        save_seen(seen_videos)

    elif not currently_live and live_state["is_live"]:
        # Stream just ended
        live_state = {"is_live": False, "video_id": None}
        save_live_state(live_state)


@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_for_new_video():
    feed = feedparser.parse(FEED_URL)

    if not feed.entries:
        return

    # Feed is newest-first; on first run just remember everything, post nothing
    is_first_run = len(seen_videos) == 0

    new_entries = [e for e in feed.entries if e.yt_videoid not in seen_videos]

    if is_first_run:
        for entry in feed.entries:
            seen_videos.add(entry.yt_videoid)
        save_seen(seen_videos)
        print("First run: caching existing videos, no announcement posted.")
        return

    # Post oldest-of-the-new first, so order in chat makes sense
    for entry in reversed(new_entries):
        channel = client.get_channel(CHANNEL_ID)
        if channel is None:
            print("Could not find Discord channel — check DISCORD_CHANNEL_ID and bot permissions.")
            continue

        video_url = entry.link
        title = entry.title
        author = entry.author
        thumbnail_url = entry.media_thumbnail[0]["url"] if entry.get("media_thumbnail") else None

        embed = discord.Embed(
            title=title,
            url=video_url,
            description=f"New video from **{author}**!",
            color=discord.Color.red(),
        )
        if thumbnail_url:
            embed.set_image(url=thumbnail_url)

        await channel.send(content=f"📹 New video is up! {video_url}", embed=embed)

        seen_videos.add(entry.yt_videoid)

    if new_entries:
        save_seen(seen_videos)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    if not check_for_new_video.is_running():
        check_for_new_video.start()
    if not check_for_live_stream.is_running():
        check_for_live_stream.start()


client.run(DISCORD_TOKEN)
