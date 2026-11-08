"""Nickname moderation commands with Discord hierarchy validation."""

from __future__ import annotations

import discord
from discord.ext import commands

from core.checks import has_guild_permission
from core.permissions import validate_nickname_target
from embeds.moderation import success_embed


MAX_NICKNAME_LENGTH = 32


class NicknameModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _bot_member(self, guild: discord.Guild) -> discord.Member:
        if guild.me is not None:
            return guild.me
        if self.bot.user is None:
            raise RuntimeError("The bot user is not available yet.")
        return await guild.fetch_member(self.bot.user.id)

    @commands.command(name="nick")
    @commands.guild_only()
    @has_guild_permission("manage_nicknames")
    async def nick(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        nickname: str,
    ) -> None:
        """Change a member's nickname to 1–32 non-whitespace characters."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        nickname = nickname.strip()
        if not nickname:
            raise commands.BadArgument(
                "Nickname cannot be empty; use resetnick to clear it."
            )
        if len(nickname) > MAX_NICKNAME_LENGTH:
            raise commands.BadArgument(
                f"Nickname must be {MAX_NICKNAME_LENGTH} characters or fewer."
            )
        bot_member = await self._bot_member(ctx.guild)
        validate_nickname_target(ctx.guild, target, ctx.author, bot_member)
        await target.edit(
            nick=nickname,
            reason=f"Nickname changed by moderator {ctx.author.id}",
        )
        await ctx.send(
            embed=success_embed(
                "nick",
                target=target,
                nickname=nickname,
                guild=ctx.guild,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="resetnick")
    @commands.guild_only()
    @has_guild_permission("manage_nicknames")
    async def resetnick(
        self, ctx: commands.Context, target: discord.Member
    ) -> None:
        """Reset a member's nickname to their account display name."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        bot_member = await self._bot_member(ctx.guild)
        validate_nickname_target(ctx.guild, target, ctx.author, bot_member)
        await target.edit(
            nick=None,
            reason=f"Nickname reset by moderator {ctx.author.id}",
        )
        await ctx.send(
            embed=success_embed("resetnick", target=target, guild=ctx.guild),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NicknameModerationCog(bot))
