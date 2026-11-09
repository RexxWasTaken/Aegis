"""Bot-owner-only commands and persistent no-prefix authorization."""

from __future__ import annotations

import discord
from discord.ext import commands

from database.repositories.community import CommunityRepository


def _repository(bot: commands.Bot) -> CommunityRepository:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The AEGIS database is not initialized.")
    return repository


class OwnerCog(commands.Cog):
    """Keep bot ownership separate from guild staff and no-prefix access."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.group(
        name="noprefix",
        invoke_without_command=True,
        description="Manage users authorized to run eligible prefix commands without a prefix.",
    )
    @commands.is_owner()
    async def noprefix(self, ctx: commands.Context) -> None:
        await ctx.send("Use `noprefix add`, `remove`, `list`, or `check`.")

    @noprefix.command(name="add", description="Authorize a user for no-prefix commands.")
    @commands.is_owner()
    async def noprefix_add(self, ctx: commands.Context, user: discord.User) -> None:
        added = await _repository(self.bot).add_no_prefix_user(
            user_id=user.id,
            added_by=ctx.author.id,
        )
        message = (
            f"{user.mention} can now use eligible prefix commands without a prefix."
            if added
            else f"{user.mention} already has no-prefix access."
        )
        await ctx.send(message, allowed_mentions=discord.AllowedMentions.none())

    @noprefix.command(name="remove", description="Remove a user's no-prefix authorization.")
    @commands.is_owner()
    async def noprefix_remove(self, ctx: commands.Context, user: discord.User) -> None:
        removed = await _repository(self.bot).remove_no_prefix_user(user_id=user.id)
        message = (
            f"No-prefix access removed for {user.mention}."
            if removed
            else f"{user.mention} did not have no-prefix access."
        )
        await ctx.send(message, allowed_mentions=discord.AllowedMentions.none())

    @noprefix.command(name="list", description="List no-prefix authorized users.")
    @commands.is_owner()
    async def noprefix_list(self, ctx: commands.Context) -> None:
        user_ids = await _repository(self.bot).list_no_prefix_users()
        if not user_ids:
            await ctx.send("No users are authorized for no-prefix commands.")
            return
        lines = [f"• <@{user_id}> (`{user_id}`)" for user_id in user_ids]
        for offset in range(0, len(lines), 25):
            await ctx.send(
                "\n".join(lines[offset : offset + 25]),
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @noprefix.command(name="check", description="Check a user's no-prefix authorization.")
    @commands.is_owner()
    async def noprefix_check(self, ctx: commands.Context, user: discord.User) -> None:
        authorized = await _repository(self.bot).has_no_prefix_user(user.id)
        status = "has" if authorized else "does not have"
        await ctx.send(
            f"{user.mention} {status} no-prefix access.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.group(
        name="owner",
        invoke_without_command=True,
        description="View private AEGIS bot-owner information.",
    )
    @commands.is_owner()
    async def owner(self, ctx: commands.Context) -> None:
        await ctx.send("Use `owner stats` or `owner servers`.")

    @owner.command(name="stats", description="Show AEGIS runtime statistics.")
    @commands.is_owner()
    async def owner_stats(self, ctx: commands.Context) -> None:
        command_count = sum(1 for _ in self.bot.walk_commands())
        await ctx.send(
            f"Servers: {len(self.bot.guilds)} • Commands: {command_count} "
            f"• Gateway latency: {round(self.bot.latency * 1000)} ms"
        )

    @owner.command(name="servers", description="List servers AEGIS has joined.")
    @commands.is_owner()
    async def owner_servers(self, ctx: commands.Context) -> None:
        guilds = sorted(
            self.bot.guilds,
            key=lambda guild: (guild.member_count or 0, guild.name.casefold()),
            reverse=True,
        )
        if not guilds:
            await ctx.send("AEGIS is not in any servers.")
            return
        lines = [
            f"• {guild.name[:100]} (`{guild.id}`) — {guild.member_count or 0} members"
            for guild in guilds
        ]
        for offset in range(0, len(lines), 20):
            await ctx.send(
                "\n".join(lines[offset : offset + 20])[:1900],
                allowed_mentions=discord.AllowedMentions.none(),
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(OwnerCog(bot))
