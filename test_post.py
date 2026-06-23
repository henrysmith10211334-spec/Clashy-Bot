import os
import asyncio
import discord

# Uses the SAME env vars as the real bot — DISCORD_TOKEN and DISCORD_CHANNEL_ID
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])

intents = discord.Intents.default()
client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    channel = client.get_channel(CHANNEL_ID)

    if channel is None:
        print("Could not find that channel — check DISCORD_CHANNEL_ID and bot permissions.")
        await client.close()
        return

    # ---- Fake "new video" test post ----
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    title = "Test for Bot"
    author = "Your Test Channel"
    thumbnail_url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"

    embed = discord.Embed(
        title=title,
        url=video_url,
        description=f"New video from **{author}**!",
        color=discord.Color.red(),
    )
    embed.set_image(url=thumbnail_url)

    await channel.send(content=f"📹 New video is up! {video_url}", embed=embed)
    print("Posted fake 'new video' test message.")

    await asyncio.sleep(2)

    # ---- Fake "going live" test post ----
    live_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    live_embed = discord.Embed(
        title="Test Live Stream",
        url=live_url,
        description="🔴 **LIVE NOW**",
        color=discord.Color.from_rgb(255, 0, 0),
    )
    live_embed.set_image(url=thumbnail_url)

    await channel.send(content=f"🔴 **Going live right now!** {live_url}", embed=live_embed)
    print("Posted fake 'going live' test message.")

    await asyncio.sleep(2)
    await client.close()


client.run(DISCORD_TOKEN)
