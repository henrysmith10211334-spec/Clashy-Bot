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
