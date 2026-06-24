"""
Messages-only leveling system. Gives random XP per message (with a cooldown
so spamming doesn't farm levels), announces level-ups, and provides
/rank (graphical card) and /leaderboard (embed) slash commands.
"""
 
import os
import time
import random
import discord
from discord import app_commands
 
import db
import rank_card
from branding import EMBED_COLOR, BOT_NAME
 
XP_MIN = 8
XP_MAX = 15
XP_COOLDOWN_SECONDS = 90
 
FOOTER_TEXT = f"Leveling System • {BOT_NAME}"
 
# Optional: if unset, level-up messages post in whatever channel the
# triggering message was sent in.
LEVEL_UP_CHANNEL_ID = os.environ.get("LEVEL_UP_CHANNEL_ID")
 
 
def xp_for_level(level):
    """
    Total cumulative XP required to REACH this level.
    Level 0 = 0 XP, by design — this must hold or progress math goes negative.
    """
    return 8 * (level ** 2) + 70 * level
 
 
def level_from_xp(xp):
    """Derives the correct level purely from total XP (never trusts stale stored data)."""
    level = 0
    while xp >= xp_for_level(level + 1):
        level += 1
    return level
 
 
async def handle_message_xp(message: discord.Message, bot):
    if message.author.bot or message.guild is None:
        return
 
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT xp, last_message_at FROM levels WHERE user_id = ?",
        (message.author.id,),
    )
    row = cur.fetchone()
    now = time.time()
 
    if row is None:
        xp, last_at = 0, 0.0
    else:
        xp, last_at = row["xp"], row["last_message_at"]
 
    if now - last_at < XP_COOLDOWN_SECONDS:
        conn.close()
        return
 
    old_level = level_from_xp(xp)
    xp += random.randint(XP_MIN, XP_MAX)
    new_level = level_from_xp(xp)
 
    cur.execute(
        """
        INSERT INTO levels (user_id, xp, level, last_message_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            xp = excluded.xp,
            level = excluded.level,
            last_message_at = excluded.last_message_at
        """,
        (message.author.id, xp, new_level, now),
    )
    conn.commit()
    conn.close()
 
    if new_level > old_level:
        target_channel = message.channel
        if LEVEL_UP_CHANNEL_ID:
            override = bot.get_channel(int(LEVEL_UP_CHANNEL_ID))
            if override:
                target_channel = override
 
        embed = discord.Embed(
            description=f"{message.author.mention} just reached **Level {new_level}**! 🎉",
            color=EMBED_COLOR,
        )
        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.set_footer(text=FOOTER_TEXT)
        await target_channel.send(embed=embed)
 
 
def setup_leveling_commands(bot):
    @bot.tree.command(name="rank", description="Show your or someone else's rank card")
    @app_commands.describe(member="Whose rank to check (defaults to you)")
    async def rank(interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        await interaction.response.defer()  # image generation takes a moment
 
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT xp FROM levels WHERE user_id = ?", (member.id,))
        row = cur.fetchone()
        xp = row["xp"] if row else 0
 
        cur.execute("SELECT COUNT(*) AS cnt FROM levels WHERE xp > ?", (xp,))
        rank_position = cur.fetchone()["cnt"] + 1
        conn.close()
 
        level = level_from_xp(xp)
        level_floor = xp_for_level(level)
        level_ceiling = xp_for_level(level + 1)
        progress_in_level = xp - level_floor
        needed_for_level = level_ceiling - level_floor
 
        buffer = await rank_card.generate_rank_card(
            member, level, rank_position, progress_in_level, needed_for_level
        )
        await interaction.followup.send(file=discord.File(buffer, filename="rank.png"))
 
    @bot.tree.command(name="leaderboard", description="Show the server's XP leaderboard")
    async def leaderboard(interaction: discord.Interaction):
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, xp FROM levels ORDER BY xp DESC LIMIT 10")
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
                display_level = level_from_xp(row["xp"])
                lines.append(
                    f"{rank_label} <@{row['user_id']}> — Level {display_level} ({row['xp']} XP)"
                )
            embed.description = "\n".join(lines)
 
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.response.send_message(embed=embed)
 
