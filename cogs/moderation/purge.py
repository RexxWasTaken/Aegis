"""Confirmed message-purge commands with explicit age-safe deletion."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlsplit

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
_INVITE_PATTERN = re.compile(
    r"(?i)(?<![\w.-])(?:https?://)?(?:www\.)?"
    r"(?:discord(?:app)?\.com/invite|discord\.gg)/[a-z0-9-]+"
)
_IMAGE_EXTENSIONS = {
    ".apng", ".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"
}
_IMAGE_URL_PATTERN = re.compile(r"(?i)(?:(?:https?://)|(?:www\.))?[^\s<>]+")
_MENTION_PATTERN = re.compile(
    r"(?i)(?<!\w)<@(?:!|&)?\d+>|@(everyone|here)\b"
)


@dataclass(frozen=True)
class PurgeResult:
    selected_count: int
    deleted_count: int
    failed_count: int


def contains_link(content: str) -> bool:
    """Match explicit URLs, www links, or bare domain links—not ordinary prose."""
    return _LINK_PATTERN.search(content) is not None


def contains_invite(content: str) -> bool:
    """Match Discord invite URLs, including discord.gg and discord.com/invite."""
    return _INVITE_PATTERN.search(content) is not None


def contains_image_url(content: str) -> bool:
    """Match direct URLs whose path ends in a supported image format."""
    for match in _IMAGE_URL_PATTERN.finditer(content):
        candidate = match.group(0).rstrip(".,!?;:)]}")
        if not candidate:
            continue
        if not re.match(r"(?i)^(?:https?://|www\.)", candidate):
            continue
        normalized = candidate if "://" in candidate else f"https://{candidate}"
        try:
            path = urlsplit(normalized).path.lower()
        except ValueError:
            continue
        if any(path.endswith(extension) for extension in _IMAGE_EXTENSIONS):
            return True
    return False


def message_contains_image(message: discord.Message) -> bool:
    """Match image attachments by MIME type/name or direct image URLs."""
    for attachment in getattr(message, "attachments", ()):
        content_type = (getattr(attachment, "content_type", None) or "").lower()
        filename = (getattr(attachment, "filename", None) or "").lower()
        if content_type.startswith("image/") or any(
            filename.endswith(extension) for extension in _IMAGE_EXTENSIONS
        ):
            return True
    return contains_image_url(getattr(message, "content", ""))


def message_contains_mention(message: discord.Message) -> bool:
    """Match parsed user/role/everyone mentions, with a raw-token fallback."""
    return bool(
        getattr(message, "mentions", ())
        or getattr(message, "role_mentions", ())
        or getattr(message, "mention_everyone", False)
        or _MENTION_PATTERN.search(getattr(message, "content", ""))
    )


def parse_purge_contains_arguments(arguments: str) -> tuple[int, str]:
    """Parse optional leading count followed by a case-insensitive text filter."""
    value = arguments.strip()
    if not value:
        raise commands.BadArgument("Provide text to search for.")
    match = re.match(r"^(\d+)\s+(.+)$", value)
    if match:
        count = int(match.group(1))
        text = match.group(2).strip()
    else:
        count = MAX_PURGE_COUNT
        text = value
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if not text:
        raise commands.BadArgument("Provide text to search for.")
    if len(text) > 200:
        raise commands.BadArgument("Search text must be 200 characters or fewer.")
    return count, text


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
        match_text: str | None = None,
        after_message_id: int | None = None,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if not 1 <= count <= MAX_PURGE_COUNT:
            raise commands.BadArgument(
                f"Count must be between 1 and {MAX_PURGE_COUNT}."
            )
        await self._require_bot_permissions(ctx)
        if after_message_id is None:
            messages = await self._matching_messages(
                ctx, count=count, predicate=predicate
            )
        else:
            if after_message_id <= 0:
                raise commands.BadArgument("Provide a valid message ID.")
            try:
                anchor = await ctx.channel.fetch_message(after_message_id)
            except (discord.NotFound, discord.Forbidden) as exc:
                raise commands.BadArgument(
                    "The reference message could not be found in this channel."
                ) from exc
            messages = []
            async for message in ctx.channel.history(
                after=anchor, limit=MAX_HISTORY_SCAN, oldest_first=True
            ):
                if message.id == ctx.message.id:
                    continue
                messages.append(message)
                if len(messages) >= count:
                    break
        if not messages:
            await ctx.send(
                embed=operation_error_embed(
                    "No matching messages were found in the latest "
                    f"{MAX_HISTORY_SCAN} eligible messages.",
                    guild=ctx.guild,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        view = BulkActionConfirmationView(ctx.author.id)
        confirmation = await ctx.send(
            embed=confirmation_embed(
                command_name,
                count=len(messages),
                target=target,
                guild=ctx.guild,
                match_text=match_text,
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
                embed=operation_error_embed(message, guild=ctx.guild),
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
                    "message(s) could not be removed or were already gone.",
                    guild=ctx.guild,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        embed = success_embed(
            command_name,
            count=result.deleted_count,
            target=target,
            match_text=match_text,
            guild=ctx.guild,
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

    @commands.command(name="purgeinvites")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgeinvites(
        self, ctx: commands.Context, count: int = MAX_PURGE_COUNT
    ) -> None:
        """Delete messages containing Discord invite links after confirmation."""
        await self._run(
            ctx,
            command_name="purgeinvites",
            count=count,
            predicate=lambda message: contains_invite(message.content),
        )

    @commands.command(name="purgeimages")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgeimages(
        self, ctx: commands.Context, count: int = MAX_PURGE_COUNT
    ) -> None:
        """Delete messages with image attachments or direct image URLs."""
        await self._run(
            ctx,
            command_name="purgeimages",
            count=count,
            predicate=message_contains_image,
        )

    @commands.command(name="purgefiles")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgefiles(
        self, ctx: commands.Context, count: int = MAX_PURGE_COUNT
    ) -> None:
        """Delete messages containing any file attachment."""
        await self._run(
            ctx,
            command_name="purgefiles",
            count=count,
            predicate=lambda message: bool(getattr(message, "attachments", ())),
        )

    @commands.command(name="purgeembeds")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgeembeds(
        self, ctx: commands.Context, count: int = MAX_PURGE_COUNT
    ) -> None:
        """Delete messages that contain one or more embeds."""
        await self._run(
            ctx,
            command_name="purgeembeds",
            count=count,
            predicate=lambda message: bool(getattr(message, "embeds", ())),
        )

    @commands.command(name="purgementions")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgementions(
        self, ctx: commands.Context, count: int = MAX_PURGE_COUNT
    ) -> None:
        """Delete messages containing user, role, @everyone, or @here mentions."""
        await self._run(
            ctx,
            command_name="purgementions",
            count=count,
            predicate=message_contains_mention,
        )

    @commands.command(name="purgecontains")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgecontains(
        self, ctx: commands.Context, *, arguments: str
    ) -> None:
        """Delete messages containing text, optionally preceded by a limit."""
        count, match_text = parse_purge_contains_arguments(arguments)
        await self._run(
            ctx,
            command_name="purgecontains",
            count=count,
            match_text=match_text,
            predicate=lambda message: match_text.casefold()
            in getattr(message, "content", "").casefold(),
        )

    @commands.command(name="purgeafter")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def purgeafter(
        self,
        ctx: commands.Context,
        message_id: int,
        count: int = MAX_PURGE_COUNT,
    ) -> None:
        """Delete up to the limit of eligible messages after a message ID."""
        await self._run(
            ctx,
            command_name="purgeafter",
            count=count,
            predicate=lambda message: True,
            after_message_id=message_id,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PurgeCog(bot))
