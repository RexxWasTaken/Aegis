"""Persistent ticket panel, private-channel lifecycle, and management commands."""

from __future__ import annotations

import io
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.emoji_manager import emoji_markup
from core.errors import handle_command_error
from core.ticket_manager import TicketManager, TicketManagerError
from database.repositories.community import CommunityRepository, TicketRecord
from embeds.ticket import (
    TICKET_COLOR,
    ticket_delete_confirmation_embed,
    ticket_info_embed,
    ticket_panel_embed,
    ticket_status_embed,
    ticket_transcript_embed,
    ticket_welcome_embed,
)


_TICKET_CATEGORIES = (
    (
        "General Support",
        "Get help with a general question or account issue.",
        "ticket",
    ),
    (
        "Report a User",
        "Report a user for behavior that needs staff review.",
        "moderation",
    ),
    (
        "Partnership",
        "Ask about an official server partnership.",
        "security",
    ),
    (
        "Bug Report",
        "Report a reproducible AEGIS bot issue.",
        "warning",
    ),
    (
        "Other",
        "Contact the support team about another issue.",
        "utility",
    ),
)


def _manager(bot: commands.Bot) -> TicketManager:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The community database is not initialized.")
    return TicketManager(bot, repository)


def _is_member(value: object) -> bool:
    return isinstance(value, discord.Member)


def _success_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title=f"{emoji_markup('success')} AEGIS Support",
        description=message,
        color=TICKET_COLOR,
    )


def _error_embed(message: str) -> discord.Embed:
    return discord.Embed(
        title=f"{emoji_markup('error')} Ticket action failed",
        description=message,
        color=TICKET_COLOR,
    )


class TicketIssueSelect(discord.ui.Select):
    def __init__(self, manager: TicketManager) -> None:
        self.manager = manager
        options = [
            discord.SelectOption(
                label=label,
                value=label,
                description=description,
                emoji=discord.PartialEmoji.from_str(emoji_markup(emoji_name)),
            )
            for label, description, emoji_name in _TICKET_CATEGORIES
        ]
        super().__init__(
            placeholder="What's The Issue?",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="aegis:ticket:create",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        creator = interaction.user
        if guild is None or not _is_member(creator):
            await interaction.response.send_message(
                f"{emoji_markup('error')} Tickets can only be opened inside a server.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket: TicketRecord | None = None
        channel: discord.TextChannel | None = None
        try:
            ticket, channel = await self.manager.open_ticket(
                guild=guild,
                creator=creator,
                category=self.values[0],
            )
        except (TicketManagerError, ValueError, LookupError) as exc:
            await interaction.followup.send(
                f"{emoji_markup('error')} {exc}",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        except discord.HTTPException:
            await interaction.followup.send(
                f"{emoji_markup('error')} The ticket channel could not be created. "
                "Check the bot's channel permissions and try again.",
                ephemeral=True,
            )
            return
        try:
            await channel.send(
                embed=ticket_welcome_embed(ticket, creator=creator),
                view=TicketControlsView(self.manager),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            try:
                await self.manager.repository.set_ticket_status(
                    channel_id=channel.id,
                    status="closed",
                    closed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
                await self.manager.repository.log_ticket_event(
                    ticket_id=ticket.ticket_id,
                    guild_id=guild.id,
                    actor_id=creator.id,
                    event="Creation failed",
                    details="Ticket welcome message could not be sent.",
                )
                await channel.delete(reason="AEGIS ticket setup message could not be sent")
            except (discord.HTTPException, LookupError, ValueError):
                pass
            await interaction.followup.send(
                f"{emoji_markup('error')} The ticket could not be created. "
                "Check the bot's channel permissions and try again.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"{emoji_markup('success')} Your private ticket is ready: {channel.mention}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class TicketPanelView(discord.ui.View):
    def __init__(self, manager: TicketManager) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketIssueSelect(manager))


class TicketDeleteConfirmView(discord.ui.View):
    def __init__(
        self,
        manager: TicketManager,
        *,
        requester_id: int,
        timeout: float = 60,
    ) -> None:
        super().__init__(timeout=timeout)
        self.manager = manager
        self.requester_id = requester_id
        self.message: discord.Message | None = None

    async def _authorized(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True
        await interaction.response.send_message(
            f"{emoji_markup('error')} Only the staff member who opened this confirmation can use it.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(
        label="Confirm Delete",
        style=discord.ButtonStyle.danger,
        custom_id="aegis:ticket:delete:confirm",
    )
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._authorized(interaction):
            return
        guild = interaction.guild
        channel = interaction.channel
        actor = interaction.user
        if (
            guild is None
            or not _is_member(actor)
            or not isinstance(channel, discord.TextChannel)
        ):
            await interaction.response.send_message(
                f"{emoji_markup('error')} This confirmation must be used in the ticket channel.",
                ephemeral=True,
            )
            return
        ticket = await self.manager.repository.get_ticket(channel.id)
        if ticket is None or ticket.guild_id != guild.id:
            await interaction.response.send_message(
                f"{emoji_markup('error')} This is not a registered ticket channel.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            transcript = await self.manager.delete(
                ticket=ticket,
                channel=channel,
                actor=actor,
            )
        except (TicketManagerError, ValueError, LookupError, discord.HTTPException) as exc:
            await interaction.followup.send(
                f"{emoji_markup('error')} {exc}",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        self.stop()
        success_message = (
            f"{emoji_markup('success')} Ticket `#{ticket.ticket_id}` was deleted."
        )
        try:
            await interaction.followup.send(
                success_message,
                file=discord.File(
                    io.BytesIO(transcript),
                    filename=f"ticket-{ticket.ticket_id}-transcript.txt",
                ),
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            await interaction.followup.send(
                f"{success_message} The transcript is retained in the ticket database "
                "and could not be attached to this response.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        custom_id="aegis:ticket:delete:cancel",
    )
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._authorized(interaction):
            return
        self.stop()
        await interaction.response.edit_message(
            content="Ticket deletion cancelled.",
            embed=None,
            view=None,
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class TicketControlsView(discord.ui.View):
    def __init__(self, manager: TicketManager) -> None:
        super().__init__(timeout=None)
        self.manager = manager

    async def _ticket(self, interaction: discord.Interaction) -> TicketRecord | None:
        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message(
                f"{emoji_markup('error')} This interaction is not inside a ticket channel.",
                ephemeral=True,
            )
            return None
        ticket = await self.manager.repository.get_ticket(channel.id)
        if ticket is None:
            await interaction.response.send_message(
                f"{emoji_markup('error')} This channel is not a registered AEGIS ticket.",
                ephemeral=True,
            )
            return None
        return ticket

    async def _actor(self, interaction: discord.Interaction) -> discord.Member | None:
        if not _is_member(interaction.user):
            await interaction.response.send_message(
                f"{emoji_markup('error')} Ticket controls can only be used inside a server.",
                ephemeral=True,
            )
            return None
        return interaction.user

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.success,
        custom_id="aegis:ticket:claim",
    )
    async def claim(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        ticket = await self._ticket(interaction)
        actor = await self._actor(interaction)
        if ticket is None or actor is None:
            return
        try:
            claimed = await self.manager.claim(ticket, actor)
        except (TicketManagerError, ValueError, LookupError) as exc:
            await interaction.response.send_message(
                embed=_error_embed(str(exc)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            _success_embed(f"Ticket `#{claimed.ticket_id}` was claimed by {actor.mention}."),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.danger,
        custom_id="aegis:ticket:close",
    )
    async def close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        ticket = await self._ticket(interaction)
        actor = await self._actor(interaction)
        channel = interaction.channel
        if ticket is None or actor is None or not isinstance(channel, discord.TextChannel):
            return
        try:
            updated = await self.manager.close(ticket=ticket, channel=channel, actor=actor)
        except (TicketManagerError, ValueError, LookupError) as exc:
            await interaction.response.send_message(
                embed=_error_embed(str(exc)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=ticket_status_embed(updated, actor=actor, status="closed"),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="Reopen",
        style=discord.ButtonStyle.primary,
        custom_id="aegis:ticket:reopen",
    )
    async def reopen(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        ticket = await self._ticket(interaction)
        actor = await self._actor(interaction)
        channel = interaction.channel
        if ticket is None or actor is None or not isinstance(channel, discord.TextChannel):
            return
        try:
            updated = await self.manager.reopen(ticket=ticket, channel=channel, actor=actor)
        except (TicketManagerError, ValueError, LookupError, discord.HTTPException) as exc:
            await interaction.response.send_message(
                embed=_error_embed(str(exc)),
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            embed=ticket_status_embed(updated, actor=actor, status="open"),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @discord.ui.button(
        label="Delete",
        style=discord.ButtonStyle.secondary,
        custom_id="aegis:ticket:delete",
    )
    async def delete(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        ticket = await self._ticket(interaction)
        actor = await self._actor(interaction)
        if ticket is None or actor is None:
            return
        try:
            if not await self.manager.is_staff(ticket, actor):
                raise TicketManagerError("Only ticket staff can delete a ticket.")
        except (TicketManagerError, ValueError, LookupError) as exc:
            await interaction.response.send_message(
                embed=_error_embed(str(exc)),
                ephemeral=True,
            )
            return
        view = TicketDeleteConfirmView(
            self.manager,
            requester_id=actor.id,
        )
        await interaction.response.send_message(
            embed=ticket_delete_confirmation_embed(ticket),
            view=view,
            ephemeral=True,
        )
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            view.stop()


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = _manager(bot)

    async def cog_load(self) -> None:
        self.bot.add_view(TicketPanelView(self.manager))
        self.bot.add_view(TicketControlsView(self.manager))

    async def cog_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        original = getattr(error, "original", error)
        if isinstance(original, (TicketManagerError, ValueError, LookupError)):
            embed = _error_embed(str(original))
            if ctx.interaction is not None:
                await ctx.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
            return
        await handle_command_error(ctx, error)

    def _require_guild(self, ctx: commands.Context) -> discord.Guild:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return ctx.guild

    async def _ticket_for_context(
        self,
        ctx: commands.Context,
    ) -> tuple[TicketRecord, discord.TextChannel, discord.Member]:
        guild = self._require_guild(ctx)
        if not isinstance(ctx.author, discord.Member):
            raise commands.NoPrivateMessage()
        if not isinstance(ctx.channel, discord.TextChannel):
            raise commands.BadArgument("Run this command inside a ticket text channel.")
        ticket = await self.manager.repository.get_ticket(ctx.channel.id)
        if ticket is None or ticket.guild_id != guild.id:
            raise TicketManagerError("This channel is not a registered AEGIS ticket.")
        return ticket, ctx.channel, ctx.author

    @commands.hybrid_group(
        name="ticket",
        description="Create and manage AEGIS support tickets.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def ticket(self, ctx: commands.Context) -> None:
        """Show the ticket command group usage."""
        embed = discord.Embed(
            title=f"{emoji_markup('ticket')} AEGIS Support",
            description=(
                "Use `a!ticket panel` to post the support menu, or `a!ticket info` "
                "inside a ticket channel."
            ),
            color=TICKET_COLOR,
        )
        if ctx.interaction is not None:
            await ctx.send(embed=embed, ephemeral=True)
        else:
            await ctx.send(embed=embed)

    @ticket.command(name="setup", description="Configure the ticket staff role and channels.")
    @app_commands.describe(
        staff_role="Role allowed to manage tickets.",
        category="Optional category for newly opened ticket channels.",
        log_channel="Optional channel for ticket event logs and transcripts.",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def setup(
        self,
        ctx: commands.Context,
        staff_role: discord.Role,
        category: discord.CategoryChannel | None = None,
        log_channel: discord.TextChannel | None = None,
    ) -> None:
        guild = self._require_guild(ctx)
        if staff_role.id == guild.default_role.id:
            raise commands.BadArgument("Choose a staff role other than @everyone.")
        await self.manager.repository.set_ticket_config(
            guild_id=guild.id,
            staff_role_id=staff_role.id,
            category_id=category.id if category else None,
            log_channel_id=log_channel.id if log_channel else None,
        )
        details = f"Ticket staff role set to {staff_role.mention}."
        if category is not None:
            details += f"\nTicket category: {category.name}"
        if log_channel is not None:
            details += f"\nTicket event logs: {log_channel.mention}"
        await ctx.send(
            embed=_success_embed(details),
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )

    @ticket.command(name="panel", description="Post the AEGIS Support ticket panel.")
    @app_commands.describe(channel="Optional text channel for the support menu.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def panel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
    ) -> None:
        guild = self._require_guild(ctx)
        await self.manager.configuration(guild.id)
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel for the ticket panel.")
        message = await target.send(
            embed=ticket_panel_embed(),
            view=TicketPanelView(self.manager),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await ctx.send(
            embed=_success_embed(f"AEGIS Support panel posted: {message.jump_url}"),
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )

    @ticket.command(name="close", description="Close the current AEGIS support ticket.")
    @commands.guild_only()
    async def close(self, ctx: commands.Context) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        updated = await self.manager.close(ticket=ticket, channel=channel, actor=actor)
        await ctx.send(
            embed=ticket_status_embed(updated, actor=actor, status="closed"),
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )

    @ticket.command(name="reopen", description="Reopen the current AEGIS support ticket.")
    @commands.guild_only()
    async def reopen(self, ctx: commands.Context) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        updated = await self.manager.reopen(ticket=ticket, channel=channel, actor=actor)
        await ctx.send(
            embed=ticket_status_embed(updated, actor=actor, status="open"),
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )

    @ticket.command(name="claim", description="Claim the current support ticket as staff.")
    @commands.guild_only()
    async def claim(self, ctx: commands.Context) -> None:
        ticket, _, actor = await self._ticket_for_context(ctx)
        claimed = await self.manager.claim(ticket, actor)
        await ctx.send(
            embed=_success_embed(
                f"Ticket `#{claimed.ticket_id}` was claimed by {actor.mention}."
            ),
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )

    @ticket.command(
        name="delete",
        description="Delete the current support ticket after confirmation.",
    )
    @commands.guild_only()
    async def delete(self, ctx: commands.Context) -> None:
        ticket, _, actor = await self._ticket_for_context(ctx)
        if not await self.manager.is_staff(ticket, actor):
            raise TicketManagerError("Only ticket staff can delete a ticket.")
        view = TicketDeleteConfirmView(self.manager, requester_id=actor.id)
        message = await ctx.send(
            embed=ticket_delete_confirmation_embed(ticket),
            view=view,
            ephemeral=ctx.interaction is not None,
        )
        view.message = message

    @ticket.command(name="add", description="Add a member to the current support ticket.")
    @app_commands.describe(member="Server member to give ticket access.")
    @commands.guild_only()
    async def add(self, ctx: commands.Context, member: discord.Member) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        await self.manager.add_member(
            ticket=ticket,
            channel=channel,
            actor=actor,
            member=member,
        )
        await ctx.send(
            embed=_success_embed(
                f"{member.mention} was added to ticket `#{ticket.ticket_id}`."
            ),
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )

    @ticket.command(
        name="remove",
        description="Remove a member from the current support ticket.",
    )
    @app_commands.describe(member="Server member whose ticket access will be removed.")
    @commands.guild_only()
    async def remove(self, ctx: commands.Context, member: discord.Member) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        await self.manager.remove_member(
            ticket=ticket,
            channel=channel,
            actor=actor,
            member=member,
        )
        await ctx.send(
            embed=_success_embed(
                f"{member.mention} was removed from ticket `#{ticket.ticket_id}`."
            ),
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )

    @ticket.command(
        name="transcript",
        description="Export a transcript of the current support ticket.",
    )
    @commands.guild_only()
    async def transcript(self, ctx: commands.Context) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        if not await self.manager.can_access(ticket, actor):
            raise TicketManagerError(
                "Only the ticket creator or configured ticket staff can export a transcript."
            )
        transcript = await self.manager.transcript_bytes(channel)
        file = discord.File(
            io.BytesIO(transcript),
            filename=f"ticket-{ticket.ticket_id}-transcript.txt",
        )
        await ctx.send(
            embed=ticket_transcript_embed(ticket, actor=actor),
            file=file,
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )

    @ticket.command(name="info", description="Show details for the current support ticket.")
    @commands.guild_only()
    async def info(self, ctx: commands.Context) -> None:
        ticket, _, actor = await self._ticket_for_context(ctx)
        if not await self.manager.can_access(ticket, actor):
            raise TicketManagerError(
                "Only the ticket creator or configured ticket staff can view ticket information."
            )
        guild = self._require_guild(ctx)
        creator = guild.get_member(ticket.creator_id)
        claimer = guild.get_member(ticket.claimed_by) if ticket.claimed_by else None
        await ctx.send(
            embed=ticket_info_embed(
                ticket,
                creator_name=creator.mention if creator else f"<@{ticket.creator_id}>",
                claimed_name=(
                    claimer.mention
                    if claimer is not None
                    else f"<@{ticket.claimed_by}>"
                    if ticket.claimed_by is not None
                    else None
                ),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
            ephemeral=ctx.interaction is not None,
        )


async def setup(bot: commands.Bot) -> None:
    cog = TicketCog(bot)
    await bot.add_cog(cog)
    permission_labels = {
        "close": "Ticket creator or configured ticket staff",
        "reopen": "Configured ticket staff role or Manage Server",
        "claim": "Configured ticket staff role or Manage Server",
        "delete": "Configured ticket staff role or Manage Server",
        "add": "Configured ticket staff role or Manage Server",
        "remove": "Configured ticket staff role or Manage Server",
        "transcript": "Ticket creator or configured ticket staff",
        "info": "Ticket creator or configured ticket staff",
        "panel": "Manage Server",
        "setup": "Manage Server",
    }
    app_group = bot.tree.get_command("ticket")
    for name, description in permission_labels.items():
        prefix_command = bot.get_command(f"ticket {name}")
        if prefix_command is not None:
            prefix_command.extras["help_permissions"] = description
        slash_command = app_group.get_command(name) if app_group is not None else None
        if slash_command is not None:
            slash_command.extras["help_permissions"] = description
