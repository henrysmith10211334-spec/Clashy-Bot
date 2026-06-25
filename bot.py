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
GUILD_ID = os.environ.get("GUILD_ID")  # optional — set for instant slash command sync while testing

intents = discord.Intents.default()
intents.members = True  # required for invite tracking — also enable "Server Members Intent" in the Dev Portal

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

leveling.setup_leveling_commands(bot)
invites.setup_invite_commands(bot)

# UPDATED: now receives manual_check_for_new_video
start_youtube_tasks, build_youtube_web_app, manual_check = youtube.setup_youtube(bot)
bot.youtube_manual_check = manual_check

_synced = False


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"Slash command error in /{interaction.command.name if interaction.command else '?'}: {error}")
    traceback.print_exception(type(error), error, error.__traceback__)

    message = f"⚠️ Something went wrong running this command:\n```{error}```"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except Exception as inner:
        print(f"Also failed to report the error to Discord: {inner}")


@bot.event
async def on_ready():
    global _synced
    print(f"Logged in as {bot.user}")

    db.init_db()
    await invites.cache_all_guild_invites(bot)
    start_youtube_tasks()

    if not _synced:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild_obj)
            await bot.tree.sync(guild=guild_obj)
            print(f"Slash commands synced instantly to guild {GUILD_ID}")
        else:
            await bot.tree.sync()
            print("Slash commands synced globally (can take up to an hour to show up)")
        _synced = True


@bot.event
async def on_message(message: discord.Message):
    await leveling.handle_message_xp(message, bot)
    await bot.process_commands(message)


@bot.event
async def on_member_join(member: discord.Member):
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
