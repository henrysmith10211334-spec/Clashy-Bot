"""
Invite tracker. Caches each guild's invite use-counts, and on member join
compares the new counts to find which invite was used (and therefore who
invited them). Logs it to LOG_CHANNEL_ID and tracks totals per inviter.

Requires:
- The bot to have the "Manage Server" permission (to read invite use counts)
- "Server Members Intent" enabled in the Discord Developer Portal (for
  on_member_join to fire at all)
"""

import os
import discord
from discord import app_commands

import db

LOG_CHANNEL_ID = int(os.environ["LOG_CHANNEL_ID"])

# guild_id -> {invite_code: uses}
_invite_cache = {}


async def cache_guild_invites(guild: discord.Guild):
    try:
        invites = await guild.invites()
        _invite_cache[guild.id] = {invite.code: (invite.uses or 0) for invite in invites}
    except discord.Forbidden:
        print(
            f"Missing permission to fetch invites for '{guild.name}' — "
            "the bot needs the 'Manage Server' permission."
        )


async def cache_all_guild_invites(bot):
    for guild in bot.guilds:
        await cache_guild_invites(guild)


async def handle_member_join(member: discord.Member, bot):
    guild = member.guild
    before = _invite_cache.get(guild.id, {})

    try:
        current_invites = await guild.invites()
    except discord.Forbidden:
        print("Missing permission to fetch invites — can't determine inviter.")
        return

    inviter = None
    for invite in current_invites:
        uses = invite.uses or 0
        if uses > before.get(invite.code, 0):
            inviter = invite.inviter
            break

    # Refresh the cache regardless of whether we found a match
    _invite_cache[guild.id] = {inv.code: (inv.uses or 0) for inv in current_invites}

    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel is None:
        print("Could not find LOG_CHANNEL_ID channel — check the env var and bot permissions.")
        return

    if inviter:
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO invites (user_id, invite_count) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET invite_count = invite_count + 1
            """,
            (inviter.id,),
        )
        conn.commit()
        cur.execute("SELECT invite_count FROM invites WHERE user_id = ?", (inviter.id,))
        total = cur.fetchone()["invite_count"]
        conn.close()

        await log_channel.send(
            f"📥 {member.mention} joined — invited by **{inviter.mention}** (now {total} invites)"
        )
    else:
        await log_channel.send(
            f"📥 {member.mention} joined — inviter unknown (vanity URL or expired invite)"
        )


def setup_invite_commands(bot):
    @bot.tree.command(name="invites", description="Check how many people someone has invited")
    @app_commands.describe(member="Whose invite count to check (defaults to you)")
    async def invites_cmd(interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT invite_count FROM invites WHERE user_id = ?", (member.id,))
        row = cur.fetchone()
        conn.close()

        count = row["invite_count"] if row else 0
        await interaction.response.send_message(
            f"**{member.display_name}** has invited **{count}** member(s)."
        )

    @bot.tree.command(name="invite-leaderboard", description="Show the server's top inviters")
    async def invite_leaderboard(interaction: discord.Interaction):
        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, invite_count FROM invites ORDER BY invite_count DESC LIMIT 10")
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("No invites tracked yet.")
            return

        lines = [
            f"**#{i}** <@{row['user_id']}> — {row['invite_count']} invites"
            for i, row in enumerate(rows, start=1)
        ]
        await interaction.response.send_message("\n".join(lines))

    # ---------- admin-only adjustments ----------

    def _is_admin(interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.manage_guild

    @bot.tree.command(name="invites-add", description="[Admin] Add or remove invites from a member's total")
    @app_commands.describe(member="Who to adjust", amount="Amount to add (negative number to subtract)")
    @app_commands.default_permissions(manage_guild=True)
    async def invites_add(interaction: discord.Interaction, member: discord.Member, amount: int):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to use this.", ephemeral=True
            )
            return

        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO invites (user_id, invite_count) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET invite_count = MAX(invite_count + ?, 0)
            """,
            (member.id, max(amount, 0), amount),
        )
        conn.commit()
        cur.execute("SELECT invite_count FROM invites WHERE user_id = ?", (member.id,))
        total = cur.fetchone()["invite_count"]
        conn.close()

        await interaction.response.send_message(
            f"Adjusted **{member.display_name}**'s invites by {amount:+d} — now **{total}** total."
        )

    @bot.tree.command(name="invites-reset", description="[Admin] Reset one member's invite count to 0")
    @app_commands.describe(member="Who to reset")
    @app_commands.default_permissions(manage_guild=True)
    async def invites_reset(interaction: discord.Interaction, member: discord.Member):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to use this.", ephemeral=True
            )
            return

        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO invites (user_id, invite_count) VALUES (?, 0)
            ON CONFLICT(user_id) DO UPDATE SET invite_count = 0
            """,
            (member.id,),
        )
        conn.commit()
        conn.close()

        await interaction.response.send_message(f"Reset **{member.display_name}**'s invites to 0.")

    @bot.tree.command(name="invites-reset-all", description="[Admin] Reset EVERYONE's invite count to 0")
    @app_commands.describe(confirm="Set to True to actually do this (safety check)")
    @app_commands.default_permissions(manage_guild=True)
    async def invites_reset_all(interaction: discord.Interaction, confirm: bool = False):
        if not _is_admin(interaction):
            await interaction.response.send_message(
                "You need the **Manage Server** permission to use this.", ephemeral=True
            )
            return

        if not confirm:
            await interaction.response.send_message(
                "This resets **everyone's** invite count to 0. Run again with `confirm: True` to proceed.",
                ephemeral=True,
            )
            return

        conn = db.get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM invites")
        conn.commit()
        conn.close()

        await interaction.response.send_message("✅ All invite counts have been reset to 0.")
