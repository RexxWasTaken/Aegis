"""Ticket setup, persistent support panels, and ticket management commands."""

from __future__ import annotations

import io
from datetime import datetime, timezone

import discord
from discord.ext import commands

from core.emoji_manager import emoji_markup
from core.ticket_manager import TicketManager, TicketManagerError
from database.repositories.community import CommunityRepository, TicketRecord
from embeds.ticket import TICKET_COLOR, ticket_panel_embed, ticket_welcome_embed


_TICKET_CATEGORIES = (
    ("General Support", "ticket"),
    ("Report a User", "moderation"),
    ("Partnership", "config"),
    ("Bug Report", "warning"),
    ("Other", "folder"),
)


def _manager(bot: commands.Bot) -> TicketManager:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The community database is not initialized.")
    return TicketManager(bot, repository)


def _is_member(value: object) -> bool:
    return isinstance(value, discord.Member)


class TicketIssueSelect(discord.ui.Select):
    def __init__(self, manager: TicketManager) -> None:
        self.manager = manager
        options = [
            discord.SelectOption(
                label=label,
                value=label,
                emoji=discord.PartialEmoji.from_str(emoji_markup(emoji_name)),
            )
            for label, emoji_name in _TICKET_CATEGORIES
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
                "Tickets can only be opened inside a server.",
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
        except TicketManagerError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except discord.HTTPException:
            await interaction.followup.send(
                "The ticket channel could not be created. Check the bot's channel "
                "permissions and custom emoji access, then try again.",
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
                "The ticket could not be created. Check the bot's channel permissions "
                "and custom emoji access, then try again.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Your private ticket is ready: {channel.mention}",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class TicketPanelView(discord.ui.View):
    def __init__(self, manager: TicketManager) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketIssueSelect(manager))


class TicketControlsView(discord.ui.View):
    def __init__(self, manager: TicketManager) -> None:
        super().__init__(timeout=None)
        self.manager = manager

    async def _ticket(self, interaction: discord.Interaction) -> TicketRecord | None:
        channel = interaction.channel
        if channel is None:
            await interaction.response.send_message(
                "This interaction is not inside a ticket channel.",
                ephemeral=True,
            )
            return None
        ticket = await self.manager.repository.get_ticket(channel.id)
        if ticket is None:
            await interaction.response.send_message(
                "This channel is not a registered AEGIS ticket.",
                ephemeral=True,
            )
            return None
        return ticket

    async def _actor(self, interaction: discord.Interaction) -> discord.Member | None:
        if not _is_member(interaction.user):
            await interaction.response.send_message(
                "Ticket controls can only be used inside a server.",
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
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Ticket `#{claimed.ticket_id}` was claimed by {actor.mention}.",
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
            updated = await self.manager.close(
                ticket=ticket,
                channel=channel,
                actor=actor,
            )
        except (TicketManagerError, ValueError, LookupError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Ticket `#{updated.ticket_id}` is now closed.",
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
            updated = await self.manager.reopen(
                ticket=ticket,
                channel=channel,
                actor=actor,
            )
        except (TicketManagerError, ValueError, LookupError) as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message(
            f"Ticket `#{updated.ticket_id}` is open again.",
            allowed_mentions=discord.AllowedMentions.none(),
        )


class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = _manager(bot)

    async def cog_load(self) -> None:
        self.bot.add_view(TicketPanelView(self.manager))
        self.bot.add_view(TicketControlsView(self.manager))

    def _require_guild(self, ctx: commands.Context) -> discord.Guild:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return ctx.guild

    async def _ticket_for_context(
        self, ctx: commands.Context
    ) -> tuple[TicketRecord, discord.TextChannel, discord.Member]:
        guild = self._require_guild(ctx)
        if not isinstance(ctx.author, discord.Member):
            raise commands.NoPrivateMessage()
        if not isinstance(ctx.channel, discord.TextChannel):
            raise commands.BadArgument("Run this command inside a ticket text channel.")
        ticket = await self.manager.repository.get_ticket(ctx.channel.id)
        if ticket is None:
            raise TicketManagerError("This channel is not a registered AEGIS ticket.")
        return ticket, ctx.channel, ctx.author

    @commands.hybrid_command(
        name="ticketsetup",
        description="Configure the AEGIS ticket staff role and channels.",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def ticketsetup(
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
            embed=discord.Embed(
                title=f"{emoji_markup('success')} Ticket setup saved",
                description=details,
                color=TICKET_COLOR,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="ticketpanel",
        description="Post the AEGIS Support Center ticket panel.",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def ticketpanel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
    ) -> None:
        guild = self._require_guild(ctx)
        await self.manager.configuration(guild.id)
        target = channel or ctx.channel
        if not isinstance(target, discord.TextChannel):
            raise commands.BadArgument("Choose a text channel for the ticket panel.")
        try:
            message = await target.send(
                embed=ticket_panel_embed(),
                view=TicketPanelView(self.manager),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            raise TicketManagerError(
                f"The ticket panel could not be posted. Check custom emoji access "
                f"for {emoji_markup('ticket')} and the bot's channel permissions."
            ) from exc
        await ctx.send(
            f"AEGIS Support Center posted: {message.jump_url}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="ticketclose",
        description="Close the current AEGIS support ticket.",
    )
    @commands.guild_only()
    async def ticketclose(self, ctx: commands.Context) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        updated = await self.manager.close(ticket=ticket, channel=channel, actor=actor)
        await ctx.send(f"Ticket `#{updated.ticket_id}` is now closed.")

    @commands.hybrid_command(
        name="ticketreopen",
        description="Reopen the current AEGIS support ticket.",
    )
    @commands.guild_only()
    async def ticketreopen(self, ctx: commands.Context) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        updated = await self.manager.reopen(ticket=ticket, channel=channel, actor=actor)
        await ctx.send(f"Ticket `#{updated.ticket_id}` is open again.")

    @commands.hybrid_command(
        name="ticketadd",
        description="Add a server member to the current support ticket.",
    )
    @commands.guild_only()
    async def ticketadd(self, ctx: commands.Context, member: discord.Member) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        await self.manager.add_member(
            ticket=ticket,
            channel=channel,
            actor=actor,
            member=member,
        )
        await ctx.send(
            f"{member.mention} was added to ticket `#{ticket.ticket_id}`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="ticketremove",
        description="Remove a server member from the current support ticket.",
    )
    @commands.guild_only()
    async def ticketremove(self, ctx: commands.Context, member: discord.Member) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        await self.manager.remove_member(
            ticket=ticket,
            channel=channel,
            actor=actor,
            member=member,
        )
        await ctx.send(
            f"{member.mention} was removed from ticket `#{ticket.ticket_id}`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="tickettranscript",
        description="Export a transcript of the current support ticket.",
    )
    @commands.guild_only()
    async def tickettranscript(self, ctx: commands.Context) -> None:
        ticket, channel, actor = await self._ticket_for_context(ctx)
        if actor.id != ticket.creator_id and not await self.manager.is_staff(ticket, actor):
            raise TicketManagerError("Only the ticket creator or ticket staff can export a transcript.")
        transcript = await self.manager.transcript_bytes(channel)
        file = discord.File(
            io.BytesIO(transcript),
            filename=f"ticket-{ticket.ticket_id}-transcript.txt",
        )
        await ctx.send(file=file, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCog(bot))
