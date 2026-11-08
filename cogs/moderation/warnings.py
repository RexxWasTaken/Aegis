"""Persistent, guild-scoped warning commands."""

from __future__ import annotations

import discord
from discord.ext import commands

from cogs.moderation.utilities import BulkActionConfirmationView
from core.checks import has_guild_permission
from embeds.moderation import (
    confirmation_embed,
    success_embed,
    warning_history_embeds,
    warning_list_embed,
    warning_stats_embed,
)
from embeds.moderation_errors import operation_error_embed
from services.moderation_service import ModerationService


class WarningHistoryView(discord.ui.View):
    """Author-only pagination for one member's full warning history."""

    def __init__(self, author_id: int, pages: list[discord.Embed]) -> None:
        super().__init__(timeout=120)
        self.author_id = author_id
        self.pages = pages
        self.page = 0

    async def _show_page(
        self, interaction: discord.Interaction, offset: int
    ) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the moderator who requested this history can turn its pages.",
                ephemeral=True,
            )
            return
        self.page = (self.page + offset) % len(self.pages)
        await interaction.response.edit_message(
            embed=self.pages[self.page], view=self
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._show_page(interaction, -1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._show_page(interaction, 1)


class WarningListView(discord.ui.View):
    """Author-only, database-backed pagination for the guild warning list."""

    def __init__(
        self,
        *,
        author_id: int,
        service: ModerationService,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member | None,
        total: int,
        page_size: int,
    ) -> None:
        super().__init__(timeout=120)
        self.author_id = author_id
        self.service = service
        self.guild = guild
        self.moderator = moderator
        self.target = target
        self.total = total
        self.page_size = page_size
        self.page = 1

    async def _show_page(
        self, interaction: discord.Interaction, offset: int
    ) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the moderator who requested this list can turn its pages.",
                ephemeral=True,
            )
            return
        page_count = max(1, (self.total + self.page_size - 1) // self.page_size)
        self.page = ((self.page - 1 + offset) % page_count) + 1
        records, _ = await self.service.warning_page(
            guild=self.guild,
            moderator=self.moderator,
            target=self.target,
            limit=self.page_size,
            offset=(self.page - 1) * self.page_size,
        )
        await interaction.response.edit_message(
            embed=warning_list_embed(
                records,
                total=self.total,
                page=self.page,
                page_size=self.page_size,
                target=self.target,
            ),
            view=self,
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary)
    async def previous(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._show_page(interaction, -1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary)
    async def next(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        await self._show_page(interaction, 1)


class WarningCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _service(self) -> ModerationService:
        service = getattr(self.bot, "moderation_service", None)
        if service is None:
            raise RuntimeError("The moderation service is not initialized.")
        return service

    @commands.command(name="warn")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def warn(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Persist a warning for a member in this server."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        warning = await self._service().warn_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
            reason=reason,
        )
        await ctx.send(
            embed=success_embed(
                "warn", target=target, reason=warning.reason, warning_id=warning.warning_id
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="unwarn")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def unwarn(
        self,
        ctx: commands.Context,
        target: discord.Member,
        warning_id: int,
    ) -> None:
        """Remove exactly one warning belonging to this member and server."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        warning = await self._service().remove_warning(
            guild=ctx.guild,
            target=target,
            warning_id=warning_id,
            moderator=ctx.author,
        )
        await ctx.send(
            embed=success_embed(
                "unwarn", target=target, warning_id=warning.warning_id
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="warnings")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def warnings(
        self,
        ctx: commands.Context,
        target: discord.Member,
    ) -> None:
        """Show the member's complete, newest-first warning history."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        records = await self._service().warnings_for_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
        )
        pages = warning_history_embeds(target, records)
        view = WarningHistoryView(ctx.author.id, pages) if len(pages) > 1 else None
        await ctx.send(
            embed=pages[0],
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="warnlist")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def warnlist(
        self,
        ctx: commands.Context,
        target: discord.Member | None = None,
    ) -> None:
        """Browse this server's warnings, optionally limited to one member."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        service = self._service()
        page_size = 8
        records, total = await service.warning_page(
            guild=ctx.guild,
            moderator=ctx.author,
            target=target,
            limit=page_size,
            offset=0,
        )
        view = (
            WarningListView(
                author_id=ctx.author.id,
                service=service,
                guild=ctx.guild,
                moderator=ctx.author,
                target=target,
                total=total,
                page_size=page_size,
            )
            if total > page_size
            else None
        )
        await ctx.send(
            embed=warning_list_embed(
                records, total=total, page=1, page_size=page_size, target=target
            ),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="warnstats")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def warnstats(self, ctx: commands.Context) -> None:
        """Summarize actual stored warning data for this server."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        stats = await self._service().warning_statistics(
            guild=ctx.guild,
            moderator=ctx.author,
        )
        await ctx.send(
            embed=warning_stats_embed(stats),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="clearwarnings")
    @commands.guild_only()
    @has_guild_permission("manage_messages")
    async def clearwarnings(
        self,
        ctx: commands.Context,
        target: discord.Member,
    ) -> None:
        """Require an author-only confirmation before deleting warning history."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        service = self._service()
        records = await service.warnings_for_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
        )
        if not records:
            await ctx.send(
                embed=operation_error_embed(f"{target.mention} has no warnings to clear."),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        view = BulkActionConfirmationView(ctx.author.id)
        confirmation = await ctx.send(
            embed=confirmation_embed(
                "clearwarnings", count=len(records), target=target
            ),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await view.wait()
        if view.value is not True:
            await confirmation.edit(view=None)
            message = (
                "Warning removal cancelled; no warnings were deleted."
                if view.value is False
                else "Warning removal confirmation expired; no warnings were deleted."
            )
            await ctx.send(
                embed=operation_error_embed(message),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await confirmation.edit(view=None)

        removed = await service.clear_warnings_for_member(
            guild=ctx.guild,
            target=target,
            moderator=ctx.author,
        )
        await ctx.send(
            embed=success_embed("clearwarnings", target=target, count=removed),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WarningCog(bot))
