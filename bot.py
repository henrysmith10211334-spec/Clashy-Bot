import asyncio
import os
import json
import re
import discord
import feedparser
import aiohttp
from aiohttp import web
from discord.ext import tasks
from urllib.parse import urlparse, urlunparse
 
# ---- CONFIG (set these in Railway "Variables" tab, not here) ----
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
YOUTUBE_CHANNEL_ID = os.environ["YOUTUBE_CHANNEL_ID"]
PUBLIC_URL = os.environ["PUBLIC_URL"].rstrip("/")  # e.g. https://yourapp.up.railway.app
PORT = int(os.environ.get("PORT", "8080"))
 
# Backup poll — WebSub handles fast detection, this just catches anything missed
CHECK_INTERVAL_MINUTES = int(os.environ.get("CHECK_INTERVAL_MINUTES", "15"))
LIVE_CHECK_INTERVAL_MINUTES = int(os.environ.get("LIVE_CHECK_INTERVAL_MINUTES", "2"))
RESUBSCRIBE_INTERVAL_HOURS = int(os.environ.get("RESUBSCRIBE_INTERVAL_HOURS", "96"))  # ~4 days; lease is 5
 
SEEN_FILE = "seen_videos.json"
LIVE_STATE_FILE = "live_state.json"
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
LIVE_URL = f"https://www.youtube.com/channel/{YOUTUBE_CHANNEL_ID}/live"
HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"
TOPIC_URL = f"https://www.youtube.com/xml/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}"
WEBHOOK_PATH = "/webhook"
 
intents = discord.Intents.default()
client = discord.Client(intents=intents)
 
 
# ---------- persistence helpers ----------
 
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
 
 
# ---------- branding / display config ----------
# Hardcoded on purpose — never pulled from the YouTube feed's author field,
# so it always says exactly this regardless of what the channel is named.
CREATOR_NAME = os.environ.get("CREATOR_NAME", "Clashy VR")
EMBED_COLOR = discord.Color(0xDDA731)  # matches the reference embed's gold accent
FOOTER_TEXT = "Youtube System • Clashy's Bot"
 
 
def extract_video_id(url):
    match = re.search(r"(?:v=|/)([\w-]{11})(?:&|$)", url)
    return match.group(1) if match else None
 
 
# ---------- announcing a new video (shared by webhook + backup poll) ----------
 
async def announce_new_video(entry):
    channel = client.get_channel(CHANNEL_ID)
    if channel is None:
        print("Could not find Discord channel — check DISCORD_CHANNEL_ID and bot permissions.")
        return False
 
    video_url = entry.link
    video_id = entry.get("yt_videoid") or extract_video_id(video_url)
    thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg" if video_id else None
 
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
    return True
 
 
# ---------- WebSub (PubSubHubbub) subscription ----------
 
def build_callback_url():
    """
    pubsubhubbub.appspot.com rejects callback URLs that don't have an
    EXPLICIT port, even when the scheme implies one (443 for https).
    So we add it ourselves if missing.
    """
    parsed = urlparse(PUBLIC_URL)
    netloc = parsed.netloc
    if ":" not in netloc:
        default_port = 443 if parsed.scheme == "https" else 80
        netloc = f"{netloc}:{default_port}"
    fixed = urlunparse(parsed._replace(netloc=netloc))
    return f"{fixed}{WEBHOOK_PATH}"
 
 
async def subscribe_to_hub():
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
                    print(f"WebSub: subscription request accepted (callback: {callback_url})")
                else:
                    text = await resp.text()
                    print(f"WebSub: subscription request failed ({resp.status}): {text}")
    except Exception as e:
        print(f"WebSub: subscription request error: {e}")
 
 
@tasks.loop(hours=RESUBSCRIBE_INTERVAL_HOURS)
async def resubscribe_loop():
    await subscribe_to_hub()
 
 
# ---------- webhook server: receives push notifications from YouTube ----------
 
async def handle_webhook_get(request):
    """YouTube's hub calls this with a GET to verify subscribe requests."""
    challenge = request.query.get("hub.challenge", "")
    mode = request.query.get("hub.mode", "")
    print(f"WebSub: verification GET received (mode={mode})")
    return web.Response(text=challenge, status=200)
 
 
async def handle_webhook_post(request):
    """YouTube's hub POSTs here the moment a video is published/updated."""
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
 
 
def build_web_app():
    app = web.Application()
    app.router.add_get(WEBHOOK_PATH, handle_webhook_get)
    app.router.add_post(WEBHOOK_PATH, handle_webhook_post)
    return app
 
 
# ---------- live-stream detection (unchanged — still polling based) ----------
 
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
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        embed = discord.Embed(
            description=(
                f"**{CREATOR_NAME}** is now live\n\n"
                f"[Jump to Clashy's live stream!]({video_url})"
            ),
            color=discord.Color.from_rgb(255, 0, 0),
        )
        embed.set_image(url=f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg")
        embed.set_footer(text=FOOTER_TEXT)
        await channel.send(embed=embed)
 
        live_state = {"is_live": True, "video_id": video_id}
        save_live_state(live_state)
        seen_videos.add(video_id)
        save_seen(seen_videos)
 
    elif not currently_live and live_state["is_live"]:
        live_state = {"is_live": False, "video_id": None}
        save_live_state(live_state)
 
 
# ---------- backup polling (safety net in case a push notification is missed) ----------
 
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
 
 
# ---------- startup ----------
 
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    if not check_for_new_video.is_running():
        check_for_new_video.start()
    if not check_for_live_stream.is_running():
        check_for_live_stream.start()
    if not resubscribe_loop.is_running():
        resubscribe_loop.start()
 
 
async def main():
    app = build_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Webhook server listening on port {PORT} (path {WEBHOOK_PATH})")
 
    async with client:
        await client.start(DISCORD_TOKEN)
 
 
if __name__ == "__main__":
    asyncio.run(main())
 
