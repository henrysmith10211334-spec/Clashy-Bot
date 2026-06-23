import asyncio
import os
import json
import discord
import feedparser
from discord.ext import tasks

# ---- CONFIG (set these in Railway "Variables" tab, not here) ----
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "5"))

SEEN_FILE = "seen_videos.json"
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"

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


client.run(DISCORD_TOKEN)
