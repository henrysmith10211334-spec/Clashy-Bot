import os
import asyncio
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web

import db
import leveling
import invites
import youtube

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
PORT = int(os.environ.get("PORT", "8080"))
GUILD_ID = os.environ.get("GUILD_ID")

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Attach leveling + invite systems
leveling.setup_leveling_commands(bot)
invites.setup_invite_commands(bot)

# YouTube system
start_youtube_tasks, build_youtube_web_app, manual_check = youtube.setup_youtube(bot)
bot.youtube_manual_check = manual_check

_synced = False


@bot.tree.error
async def on_app_command_error(interaction, error):
    print(f"Slash command error: {error}")
    traceback.print_exception(type(error), error, error.__traceback__)

    msg = f"⚠️ Something went wrong:\n```{error}```"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except:
        pass


@bot.tree.command(
    name="check-now",
    description="Force the YouTube system to check for new videos immediately.",
)
@app_commands.default_permissions(administrator=True)
async def check_now(interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        await bot.youtube_manual_check()
        await interaction.followup.send("YouTube check completed.")
    except Exception as e:
        await interaction.followup.send(f"Error: {e}")

# ------------------------------------------------------------
# YT Channel Command
#-------------------------------------------------------------
@bot.tree.command(
    name="yt-stats",
    description="Show YouTube channel statistics for the configured channel."
)
async def yt_stats(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=False)

    try:
        import aiohttp
        import os

        channel_id = os.environ.get("YOUTUBE_CHANNEL_ID")
        api_key = os.environ.get("YOUTUBE_API_KEY")

        if not api_key:
            await interaction.followup.send("❌ Missing YOUTUBE_API_KEY environment variable.")
            return

        # YouTube Data API request
        url = (
            "https://www.googleapis.com/youtube/v3/channels"
            f"?part=snippet,statistics&id={channel_id}&key={api_key}"
        )

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()

        if "items" not in data or not data["items"]:
            await interaction.followup.send("❌ Could not fetch channel stats.")
            return

        info = data["items"][0]
        snippet = info.get("snippet", {})
        stats = info.get("statistics", {})

        # Basic info
        created = snippet.get("publishedAt", "Unknown")

        # Stats
        subs = stats.get("subscriberCount", "0")
        views = stats.get("viewCount", "0")
        videos = stats.get("videoCount", "0")

        # Channel profile picture
        pfp = snippet.get("thumbnails", {}).get("high", {}).get("url")

        embed = discord.Embed(
            title=f"YouTube Channel Stats — Clashy Vr",
            color=discord.Color.red()
        )

        embed.add_field(name="👥 Subscribers", value=f"{int(subs):,}", inline=True)
        embed.add_field(name="▶️ Views", value=f"{int(views):,}", inline=True)
        embed.add_field(name="🎬 Videos", value=f"{int(videos):,}", inline=True)
        embed.add_field(name="📅 Created", value="12/25/2025", inline=False)
        embed.add_field(
            name="🔗 Channel URL",
            value=f" → [Jump to Clashy Vr's Channel](https://www.youtube.com/channel/{channel_id})",
            inline=False
        )

        # Channel PFP (top right)
        if pfp:
            embed.set_thumbnail(url=pfp)

        embed.set_footer(text="YouTube System • Channel Stats")

        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"Error: {e}", ephemeral=True)
@bot.event
async def on_ready():
    global _synced
    print(f"Logged in as {bot.user}")

    db.init_db()
    await invites.cache_all_guild_invites(bot)
    start_youtube_tasks()

    if not _synced:
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"Slash commands synced instantly to guild {GUILD_ID}")
        else:
            await bot.tree.sync()
            print("Slash commands synced globally.")
        _synced = True


@bot.event
async def on_message(message):
    await leveling.handle_message_xp(message, bot)
    await bot.process_commands(message)


@bot.event
async def on_member_join(member):
    await invites.handle_member_join(member, bot)


async def main():
    app = build_youtube_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Webhook server listening on port {PORT} (path {youtube.WEBHOOK_PATH})")

    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
