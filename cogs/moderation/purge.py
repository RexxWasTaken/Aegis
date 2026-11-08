"""Confirmed message-purge commands with explicit age-safe deletion."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import discord
from discord.ext import commands

from cogs.moderation.utilities import BulkActionConfirmationView
from core.checks import has_guild_permission
from embeds.moderation import confirmation_embed, success_embed
from embeds.moderation_errors import operation_error_embed


logger = logging.getLogger(__name__)
MAX_PURGE_COUNT = 100
MAX_HISTORY_SCAN = 1000
_LINK_PATTERN = re.compile(
    r"(?i)(?<![\w@.-])(?:(?:https?://)|www\.)?"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}"
    r"(?::\d{1,5})?(?:/[^\s<>]*)?"
)


@dataclass(frozen=True)
class PurgeResult:
    selected_count: int
    deleted_count: int
    failed_count: int


def contains_link(content: str) -> bool:
    """Match explicit URLs, www links, or bare domain links—not ordinary prose."""
    return _LINK_PATTERN.search(content) is not None


class PurgeCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _require_bot_permissions(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        bot_member = ctx.guild.me
        if bot_member is None:
            if self.bot.user is None:
                raise RuntimeError("The bot user is not available yet.")
            bot_member = await ctx.guild.fetch_member(self.bot.user.id)
        permissions = ctx.channel.permissions_for(bot_member)
        required = ("view_channel", "read_message_history", "manage_messages")
        missing = [permission for permission in required if not getattr(permissions, permission, False)]
        if missing:
            raise commands.BotMissingPermissions(missing)

    async def _matching_messages(
        self,
        ctx: commands.Context,
        *,
        count: int,
        predicate: Callable[[discord.Message], bool],
    ) -> list[discord.Message]:
        selected: list[discord.Message] = []
        invocation_id = ctx.message.id
        async for message in ctx.channel.history(limit=MAX_HISTORY_SCAN):
            if message.id == invocation_id:
                continue
            if predicate(message):
                selected.append(message)
                if len(selected) >= count:
                    break
        return selected

    async def _delete_one(
        self, message: discord.Message, *, reason: str
    ) -> bool:
        try:
            await message.delete(reason=reason)
        except discord.NotFound:
            logger.info("Purge skipped message %s because it was already gone.", message.id)
            return False
        except discord.HTTPException:
            logger.warning("Could not delete message %s during purge.", message.id, exc_info=True)
            return False
        return True

    async def _delete_selected(
        self,
        ctx: commands.Context,
        messages: list[discord.Message],
        *,
        reason: str,
    ) -> PurgeResult:
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        recent: list[discord.Message] = []
        old: list[discord.Message] = []
        for message in messages:
            created_at = message.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if created_at > cutoff:
                recent.append(message)
            else:
                old.append(message)

        deleted_count = 0
        failed_count = 0
        if len(recent) >= 2:
            try:
                await ctx.channel.delete_messages(recent, reason=reason)
            except discord.Forbidden:
                logger.warning(
                    "Bot lacks permission to bulk-delete messages in channel %s.",
                    ctx.channel.id,
                    exc_info=True,
                )
                failed_count += len(recent)
            except discord.HTTPException as exc:
                logger.warning(
                    "Bulk purge failed in channel %s with HTTP %s.",
                    ctx.channel.id,
                    exc.status,
                    exc_info=True,
                )
                if exc.status == 400:
                    for message in recent:
                        if await self._delete_one(message, reason=reason):
                            deleted_count += 1
                        else:
                            failed_count += 1
                else:
                    failed_count += len(recent)
            else:
                deleted_count += len(recent)
        else:
            for message in recent:
                if await self._delete_one(message, reason=reason):
                    deleted_count += 1
                else:
                    failed_count += 1

        for message in old:
            if await self._delete_one(message, reason=reason):
                deleted_count += 1
            else:
                failed_count += 1

        return PurgeResult(
            selected_count=len(messages),
            deleted_count=deleted_count,
            failed_count=failed_count,
        )

    async def _run(
        self,
        ctx: commands.Context,
        *,
        command_name: str,
        count: int,
        predicate: Callable[[discord.Message], bool],
        target: discord.Member | None = None,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if not 1 <= count <= MAX_PURGE_COUNT:
            raise commands.BadArgument(
                f"Count must be between 1 and {MAX_PURGE_COUNT}."
            )
        await self._require_bot_permissions(ctx)
        messages = await self._matching_messages(
            ctx, count=count, predicate=predicate
        )
        if not messages:
            await ctx.send(
                embed=operation_error_embed(
                    "No matching messages were found in the latest "
                    f"{MAX_HISTORY_SCAN} messages."
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        view = BulkActionConfirmationView(ctx.author.id)
        confirmation = await ctx.send(
            embed=confirmation_embed(
                command_name, count=len(messages), target=target
            ),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await view.wait()
        if view.value is not True:
            await confirmation.edit(view=None)
            message = (
                "Purge cancelled; no messages were deleted."
                if view.value is False
                else "Purge confirmation expired; no messages were deleted."
            )
            await ctx.send(
                embed=operation_error_embed(message),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await confirmation.edit(view=None)

        reason = f"{command_name} requested by moderator {ctx.author.id}"
        result = await self._delete_selected(ctx, messages, reason=reason)
        if result.deleted_count == 0:
            await ctx.send(
                embed=operation_error_embed(
                    f"No messages were deleted. {result.failed_count} selected "
                    "message(s) could not be removed or were already gone."
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        embed = success_embed(
            command_name,
            count=result.deleted_count,
            target=target,
        )
        if result.failed_count:
            embed.description = (
                f"> Selected: {result.selected_count}\n"
                f"> Could not delete: {result.failed_count}"
            )
        await ctx.send(
            embed=embed,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="purge")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purge(self, ctx: commands.Context, count: int) -> None:
        """Delete up to 100 recent messages after explicit confirmation."""
        await self._run(
            ctx,
            command_name="purge",
            count=count,
            predicate=lambda message: True,
        )

    @commands.command(name="purgeuser")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgeuser(
        self,
        ctx: commands.Context,
        target: discord.Member,
        count: int,
    ) -> None:
        """Delete only messages authored by the selected member."""
        await self._run(
            ctx,
            command_name="purgeuser",
            count=count,
            target=target,
            predicate=lambda message: message.author.id == target.id,
        )

    @commands.command(name="purgebots")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgebots(self, ctx: commands.Context, count: int) -> None:
        """Delete messages authored by bot accounts only."""
        await self._run(
            ctx,
            command_name="purgebots",
            count=count,
            predicate=lambda message: bool(message.author.bot),
        )

    @commands.command(name="purgehumans")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgehumans(self, ctx: commands.Context, count: int) -> None:
        """Delete messages authored by human members only."""
        await self._run(
            ctx,
            command_name="purgehumans",
            count=count,
            predicate=lambda message: not bool(message.author.bot),
        )

    @commands.command(name="purgelinks")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgelinks(self, ctx: commands.Context, count: int) -> None:
        """Delete messages containing URL-like domain links."""
        await self._run(
            ctx,
            command_name="purgelinks",
            count=count,
            predicate=lambda message: contains_link(message.content),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PurgeCog(bot))
