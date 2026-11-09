"""Welcome and goodbye setup commands."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.welcome_manager import WelcomeManager
from database.repositories.community import CommunityRepository


logger = logging.getLogger(__name__)


def _manager(bot: commands.Bot) -> WelcomeManager:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The community database is not initialized.")
    return WelcomeManager(bot, repository)


class WelcomeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = _manager(bot)

    @commands.hybrid_group(
        name="welcome",
        description="Configure member welcome messages.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def welcome(self, ctx: commands.Context) -> None:
        await ctx.send("Use `welcome setup`, `welcome test`, or `welcome disable`.")

    @welcome.command(name="setup", description="Set the welcome channel and message.")
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Where new-member messages should be sent.", message="Text; variables: {user}, {username}, {server}, {member_count}.")
    async def welcome_setup(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        *,
        message: str,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self.manager.repository.set_welcome_config(
                guild_id=ctx.guild.id,
                kind="welcome",
                channel_id=channel.id,
                message=message,
            )
        except ValueError as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            f"Welcome messages are enabled in {channel.mention}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @welcome.command(name="test", description="Send a welcome-message preview.")
    @commands.has_guild_permissions(manage_guild=True)
    async def welcome_test(self, ctx: commands.Context) -> None:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            raise commands.NoPrivateMessage()
        try:
            sent = await self.manager.send_for_member(ctx.author, "welcome")
        except discord.HTTPException:
            sent = False
        message = (
            "Welcome preview sent."
            if sent
            else "Welcome is not enabled, or the configured channel is unavailable."
        )
        await ctx.send(message, allowed_mentions=discord.AllowedMentions.none())

    @welcome.command(name="disable", description="Disable welcome messages.")
    @commands.has_guild_permissions(manage_guild=True)
    async def welcome_disable(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        disabled = await self.manager.repository.disable_welcome(
            guild_id=ctx.guild.id,
            kind="welcome",
        )
        await ctx.send(
            "Welcome messages disabled."
            if disabled
            else "Welcome messages were not configured.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_group(
        name="goodbye",
        description="Configure member goodbye messages.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def goodbye(self, ctx: commands.Context) -> None:
        await ctx.send("Use `goodbye setup` or `goodbye disable`.")

    @goodbye.command(name="setup", description="Set the goodbye channel and message.")
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Where departing-member messages should be sent.", message="Text; variables: {user}, {username}, {server}, {member_count}.")
    async def goodbye_setup(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        *,
        message: str,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self.manager.repository.set_welcome_config(
                guild_id=ctx.guild.id,
                kind="goodbye",
                channel_id=channel.id,
                message=message,
            )
        except ValueError as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            f"Goodbye messages are enabled in {channel.mention}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @goodbye.command(name="disable", description="Disable goodbye messages.")
    @commands.has_guild_permissions(manage_guild=True)
    async def goodbye_disable(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        disabled = await self.manager.repository.disable_welcome(
            guild_id=ctx.guild.id,
            kind="goodbye",
        )
        await ctx.send(
            "Goodbye messages disabled."
            if disabled
            else "Goodbye messages were not configured.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        try:
            await self.manager.send_for_member(member, "welcome")
        except discord.HTTPException:
            logger.warning("Welcome message could not be delivered in guild %s.", member.guild.id)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        try:
            await self.manager.send_for_member(member, "goodbye")
        except discord.HTTPException:
            logger.warning("Goodbye message could not be delivered in guild %s.", member.guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeCog(bot))
