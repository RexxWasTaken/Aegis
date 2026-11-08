"""Member timeout commands."""

from __future__ import annotations

import discord
from discord.ext import commands

from core.checks import has_guild_permission
from embeds.moderation import success_embed
from services.moderation_service import ModerationService
from utils.duration import format_duration, parse_duration


class TimeoutCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _bot_member(self, guild: discord.Guild) -> discord.Member:
        if guild.me is not None:
            return guild.me
        if self.bot.user is None:
            raise RuntimeError("The bot user is not available yet.")
        return await guild.fetch_member(self.bot.user.id)

    def _service(self) -> ModerationService:
        service = getattr(self.bot, "moderation_service", None)
        if service is None:
            raise RuntimeError("The moderation service is not initialized.")
        return service

    @commands.command(name="timeout")
    @commands.guild_only()
    @has_guild_permission("moderate_members")
    async def timeout(
        self,
        ctx: commands.Context,
        target: discord.Member,
        duration: str,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Timeout a member for 1 second to 28 days."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            parsed_duration = parse_duration(duration)
        except ValueError as exc:
            raise commands.BadArgument(str(exc)) from exc
        case = await self._service().timeout_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            duration=parsed_duration,
            reason=reason,
        )
        await ctx.send(
            embed=success_embed(
                "timeout",
                target=target,
                reason=case.reason,
                duration=format_duration(parsed_duration),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="untimeout")
    @commands.guild_only()
    @has_guild_permission("moderate_members")
    async def untimeout(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Remove a member's active timeout."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        case = await self._service().untimeout_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("untimeout", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="mute")
    @commands.guild_only()
    @has_guild_permission("moderate_members")
    async def mute(
        self,
        ctx: commands.Context,
        target: discord.Member,
        duration: str,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Apply a timed text-and-voice mute using Discord's timeout API."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            parsed_duration = parse_duration(duration)
        except ValueError as exc:
            raise commands.BadArgument(str(exc)) from exc
        case = await self._service().timeout_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            duration=parsed_duration,
            reason=reason,
            action_type="mute",
        )
        await ctx.send(
            embed=success_embed(
                "mute",
                target=target,
                reason=case.reason,
                duration=format_duration(parsed_duration),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="unmute")
    @commands.guild_only()
    @has_guild_permission("moderate_members")
    async def unmute(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Remove a member's Discord timeout."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        case = await self._service().untimeout_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
            action_type="unmute",
        )
        await ctx.send(
            embed=success_embed("unmute", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TimeoutCog(bot))
