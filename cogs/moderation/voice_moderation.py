"""Server voice-mute moderation commands."""

from __future__ import annotations

import discord
from discord.ext import commands

from core.checks import has_guild_permission
from embeds.moderation import success_embed
from services.moderation_service import ModerationService


class VoiceModerationCog(commands.Cog):
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

    @commands.command(name="voicemute")
    @commands.guild_only()
    @has_guild_permission("mute_members")
    async def voicemute(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Server-mute a member who is connected to voice."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        case = await self._service().voicemute_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("voicemute", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="voiceunmute")
    @commands.guild_only()
    @has_guild_permission("mute_members")
    async def voiceunmute(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Remove a server voice mute from a connected member."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        case = await self._service().voiceunmute_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("voiceunmute", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="deafen")
    @commands.guild_only()
    @has_guild_permission("deafen_members")
    async def deafen(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Server-deafen a member connected to voice."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        case = await self._service().deafen_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("deafen", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceModerationCog(bot))
