"""Kick command."""

from __future__ import annotations

import discord
from discord.ext import commands

from core.checks import has_guild_permission
from embeds.moderation import success_embed
from embeds.moderation import confirmation_embed
from embeds.moderation_errors import operation_error_embed
from services.moderation_service import ModerationService
from cogs.moderation.utilities import (
    BulkActionConfirmationView,
    MAX_BULK_TARGETS,
    parse_bulk_member_arguments,
)


class KickCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="kick", aliases=("k",))
    @commands.guild_only()
    @has_guild_permission("kick_members")
    async def kick(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Kick a member and record a moderation case."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        service: ModerationService | None = getattr(self.bot, "moderation_service", None)
        if service is None:
            raise RuntimeError("The moderation service is not initialized.")
        bot_member = ctx.guild.me
        if bot_member is None:
            if self.bot.user is None:
                raise RuntimeError("The bot user is not available yet.")
            bot_member = await ctx.guild.fetch_member(self.bot.user.id)
        case = await service.kick_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=bot_member,
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("kick", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="masskick")
    @commands.guild_only()
    @has_guild_permission("kick_members")
    async def masskick(self, ctx: commands.Context, *, arguments: str) -> None:
        """Confirm, then kick 2–10 unique members with per-target audit cases."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        tokens, reason = parse_bulk_member_arguments(arguments, "masskick")
        converter = commands.MemberConverter()
        targets: list[discord.Member] = []
        for token in tokens:
            targets.append(await converter.convert(ctx, token))
        if len({target.id for target in targets}) != len(targets):
            raise commands.BadArgument("Masskick targets must be unique.")

        view = BulkActionConfirmationView(ctx.author.id)
        confirmation = await ctx.send(
            embed=confirmation_embed("masskick", count=len(targets)),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await view.wait()
        if view.value is not True:
            await confirmation.edit(view=None)
            message = (
                "Masskick cancelled; no members were kicked."
                if view.value is False
                else "Masskick confirmation expired; no members were kicked."
            )
            await ctx.send(
                embed=operation_error_embed(message),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await confirmation.edit(view=None)

        service: ModerationService | None = getattr(self.bot, "moderation_service", None)
        if service is None:
            raise RuntimeError("The moderation service is not initialized.")
        bot_member = ctx.guild.me
        if bot_member is None:
            if self.bot.user is None:
                raise RuntimeError("The bot user is not available yet.")
            bot_member = await ctx.guild.fetch_member(self.bot.user.id)
        result = await service.masskick_members(
            guild=ctx.guild,
            targets=targets,
            moderator=ctx.author,
            bot_member=bot_member,
            reason=reason,
            max_targets=MAX_BULK_TARGETS,
        )
        if not result.completed_target_ids:
            await ctx.send(
                embed=operation_error_embed(
                    f"None of the {result.attempted} members could be kicked."
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        embed = success_embed(
            "masskick",
            count=len(result.completed_target_ids),
            total=result.attempted,
        )
        if result.failed_target_ids:
            embed.description = f"> Failed: {len(result.failed_target_ids)} member(s)"
        await ctx.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(KickCog(bot))
