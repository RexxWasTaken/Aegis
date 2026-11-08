"""Ban and unban commands."""

from __future__ import annotations

import discord
from discord.ext import commands

from core.checks import has_guild_permission
from embeds.moderation import confirmation_embed, success_embed
from embeds.moderation_errors import operation_error_embed
from services.moderation_service import ModerationService
from cogs.moderation.utilities import (
    BulkActionConfirmationView,
    MAX_BULK_TARGETS,
    parse_bulk_member_arguments,
)
from utils.duration import format_duration, parse_duration


class BanCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _service(self) -> ModerationService:
        service = getattr(self.bot, "moderation_service", None)
        if service is None:
            raise RuntimeError("The moderation service is not initialized.")
        return service

    async def _bot_member(self, guild: discord.Guild) -> discord.Member:
        if guild.me is not None:
            return guild.me
        if self.bot.user is None:
            raise RuntimeError("The bot user is not available yet.")
        return await guild.fetch_member(self.bot.user.id)

    @commands.command(name="ban", aliases=("b",))
    @commands.guild_only()
    @has_guild_permission("ban_members")
    async def ban(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Ban a server member and record a moderation case."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        case = await self._service().ban_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("ban", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="unban", aliases=("ub",))
    @commands.guild_only()
    @has_guild_permission("ban_members")
    async def unban(
        self,
        ctx: commands.Context,
        target: discord.User,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Unban a user by mention or ID and record a moderation case."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        case = await self._service().unban_user(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("unban", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="softban")
    @commands.guild_only()
    @has_guild_permission("ban_members")
    async def softban(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Ban briefly to remove recent messages, then unban."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        case = await self._service().softban_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("softban", target=target, reason=case.reason),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="tempban")
    @commands.guild_only()
    @has_guild_permission("ban_members")
    async def tempban(
        self,
        ctx: commands.Context,
        target: discord.Member,
        duration: str,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Ban a member for a bounded duration and persist its expiry."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            parsed_duration = parse_duration(duration)
        except ValueError as exc:
            raise commands.BadArgument(str(exc)) from exc
        case = await self._service().tempban_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            duration=parsed_duration,
            reason=reason,
        )
        await ctx.send(
            embed=success_embed(
                "tempban",
                target=target,
                reason=case.reason,
                duration=format_duration(parsed_duration),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="massban")
    @commands.guild_only()
    @has_guild_permission("ban_members")
    async def massban(self, ctx: commands.Context, *, arguments: str) -> None:
        """Confirm, then ban 2–10 unique members with per-target audit cases."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        tokens, reason = parse_bulk_member_arguments(arguments, "massban")
        converter = commands.MemberConverter()
        targets: list[discord.Member] = []
        for token in tokens:
            targets.append(await converter.convert(ctx, token))
        if len({target.id for target in targets}) != len(targets):
            raise commands.BadArgument("Massban targets must be unique.")

        view = BulkActionConfirmationView(ctx.author.id)
        confirmation = await ctx.send(
            embed=confirmation_embed("massban", count=len(targets)),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await view.wait()
        if view.value is not True:
            await confirmation.edit(view=None)
            message = (
                "Massban cancelled; no members were banned."
                if view.value is False
                else "Massban confirmation expired; no members were banned."
            )
            await ctx.send(
                embed=operation_error_embed(message),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await confirmation.edit(view=None)

        service = self._service()
        result = await service.massban_members(
            guild=ctx.guild,
            targets=targets,
            moderator=ctx.author,
            bot_member=await self._bot_member(ctx.guild),
            reason=reason,
            max_targets=MAX_BULK_TARGETS,
        )
        if not result.completed_target_ids:
            await ctx.send(
                embed=operation_error_embed(
                    f"None of the {result.attempted} members could be banned."
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        embed = success_embed(
            "massban",
            count=len(result.completed_target_ids),
            total=result.attempted,
        )
        if result.failed_target_ids:
            embed.description = (
                f"> Failed: {len(result.failed_target_ids)} member(s)"
            )
        await ctx.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BanCog(bot))
