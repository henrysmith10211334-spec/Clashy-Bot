import os
import time
import random
import discord
from discord import app_commands

import db
from branding import EMBED_COLOR, BOT_NAME

XP_MIN = 15
XP_MAX = 25
XP_COOLDOWN_SECONDS = 60

FOOTER_TEXT = f"Leveling System • {BOT_NAME}"

# Optional: if unset, level-up messages post in whatever channel the
# triggering message was sent in.
LEVEL_UP_CHANNEL_ID = os.environ.get("LEVEL_UP_CHANNEL_ID")


def xp_for_level(level):
    """Total cumulative XP required to REACH this level."""
    return 5 * (level ** 2) + 50 * level + 100


def build_progress_bar(current, total, length=14):
    if total <= 0:
        filled = length
    else:
        filled = int(length * current / total)
    filled = max(0, min(filled, length))
    return "█" * filled + "░" * (length - filled)


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

        embed = discord.Embed(
            description=f"{message.author.mention} just reached **Level {level}**! 🎉",
            color=EMBED_COLOR,
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text=FOOTER_TEXT)
        await target_channel.send(embed=embed)


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

        xp, level = (row["xp"], row["level"]) if row else (0, 0)

        level_floor = xp_for_level(level)
        level_ceiling = xp_for_level(level + 1)
        progress_in_level = xp - level_floor
        needed_for_level = level_ceiling - level_floor
        bar = build_progress_bar(progress_in_level, needed_for_level)

        embed = discord.Embed(color=EMBED_COLOR)
        embed.set_author(name=f"{member.display_name}'s Rank", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=f"**{level}**", inline=True)
        embed.add_field(name="Total XP", value=f"**{xp}**", inline=True)
        embed.add_field(
            name="Progress to next level",
            value=f"`{bar}`\n{progress_in_level}/{needed_for_level} XP",
            inline=False,
        )
        embed.set_footer(text=FOOTER_TEXT)

        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="leaderboard", description="Show the server's XP leaderboard")
    async def leaderboard(interaction: discord.Interaction):
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, xp, level FROM levels ORDER BY xp DESC LIMIT 10")
        rows = cur.fetchall()
        conn.close()

        embed = discord.Embed(title="🏆 XP Leaderboard", color=EMBED_COLOR)

        if not rows:
            embed.description = "No one has earned XP yet."
        else:
            medals = ["🥇", "🥈", "🥉"]
            lines = []
            for i, row in enumerate(rows):
                rank_label = medals[i] if i < 3 else f"**#{i + 1}**"
                lines.append(
                    f"{rank_label} <@{row['user_id']}> — Level {row['level']} ({row['xp']} XP)"
                )
            embed.description = "\n".join(lines)

        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)
PYEOF
echo "Done."
