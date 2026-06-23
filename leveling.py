"""
Messages-only leveling system. Gives random XP per message (with a cooldown
so spamming doesn't farm levels), announces level-ups, and provides
/rank and /leaderboard slash commands.
"""

import os
import time
import random
import discord
from discord import app_commands

import db

XP_MIN = 15
XP_MAX = 25
XP_COOLDOWN_SECONDS = 60

# Optional: if unset, level-up messages post in whatever channel the
# triggering message was sent in.
LEVEL_UP_CHANNEL_ID = os.environ.get("LEVEL_UP_CHANNEL_ID")


def xp_for_level(level):
    """Total cumulative XP required to REACH this level."""
    return 5 * (level ** 2) + 50 * level + 100


async def handle_message_xp(message: discord.Message, bot):
    if message.author.bot or message.guild is None:
        return

    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT xp, level, last_message_at FROM levels WHERE user_id = ?",
        (message.author.id,),
    )
    row = cur.fetchone()
    now = time.time()

    if row is None:
        xp, level, last_at = 0, 0, 0.0
    else:
        xp, level, last_at = row["xp"], row["level"], row["last_message_at"]

    if now - last_at < XP_COOLDOWN_SECONDS:
        conn.close()
        return

    xp += random.randint(XP_MIN, XP_MAX)

    leveled_up = False
    while xp >= xp_for_level(level + 1):
        level += 1
        leveled_up = True

    cur.execute(
        """
        INSERT INTO levels (user_id, xp, level, last_message_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            xp = excluded.xp,
            level = excluded.level,
            last_message_at = excluded.last_message_at
        """,
        (message.author.id, xp, level, now),
    )
    conn.commit()
    conn.close()

    if leveled_up:
        target_channel = message.channel
        if LEVEL_UP_CHANNEL_ID:
            override = bot.get_channel(int(LEVEL_UP_CHANNEL_ID))
            if override:
                target_channel = override
        await target_channel.send(
            f"🎉 {message.author.mention} just reached **Level {level}**!"
        )


def setup_leveling_commands(bot):
    @bot.tree.command(name="rank", description="Check your or someone else's level and XP")
    @app_commands.describe(member="Whose rank to check (defaults to you)")
    async def rank(interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT xp, level FROM levels WHERE user_id = ?", (member.id,))
        row = cur.fetchone()
        conn.close()

        if row is None:
            await interaction.response.send_message(
                f"{member.display_name} hasn't earned any XP yet."
            )
            return

        xp, level = row["xp"], row["level"]
        next_threshold = xp_for_level(level + 1)
        await interaction.response.send_message(
            f"**{member.display_name}** — Level {level} ({xp}/{next_threshold} XP)"
        )

    @bot.tree.command(name="leaderboard", description="Show the server's XP leaderboard")
    async def leaderboard(interaction: discord.Interaction):
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, xp, level FROM levels ORDER BY xp DESC LIMIT 10")
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("No one has earned XP yet.")
            return

        lines = [
            f"**#{i}** <@{row['user_id']}> — Level {row['level']} ({row['xp']} XP)"
            for i, row in enumerate(rows, start=1)
        ]
        await interaction.response.send_message("\n".join(lines))
