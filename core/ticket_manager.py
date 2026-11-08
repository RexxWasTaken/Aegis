"""Private-channel ticket lifecycle and persistent event logging."""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

from database.repositories.community import (
    CommunityRepository,
    TicketConfig,
    TicketRecord,
)
from embeds.ticket import ticket_event_embed

if TYPE_CHECKING:
    from discord.ext import commands


class TicketManagerError(RuntimeError):
    """A ticket operation could not be completed safely."""


class TicketManager:
    def __init__(self, bot: commands.Bot, repository: CommunityRepository) -> None:
        self.bot = bot
        self.repository = repository

    async def configuration(self, guild_id: int) -> TicketConfig:
        config = await self.repository.get_ticket_config(guild_id)
        if config is None:
            raise TicketManagerError(
                "Ticket setup is missing. An administrator must run ticketsetup first."
            )
        return config

    async def open_ticket(
        self,
        *,
        guild: discord.Guild,
        creator: discord.Member,
        category: str,
    ) -> tuple[TicketRecord, discord.TextChannel]:
        config = await self.configuration(guild.id)
        existing = await self.repository.get_open_ticket(
            guild_id=guild.id, creator_id=creator.id
        )
        if existing is not None:
            channel = guild.get_channel(existing.channel_id)
            if isinstance(channel, discord.TextChannel):
                raise TicketManagerError(
                    f"You already have an open ticket: {channel.mention}"
                )
            await self.repository.set_ticket_status(
                channel_id=existing.channel_id,
                status="closed",
                closed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )

        staff_role = guild.get_role(config.staff_role_id)
        if staff_role is None:
            raise TicketManagerError(
                "The configured ticket staff role no longer exists. Run ticketsetup again."
            )
        category_channel = (
            guild.get_channel(config.category_id) if config.category_id is not None else None
        )
        if category_channel is not None and not isinstance(
            category_channel, discord.CategoryChannel
        ):
            raise TicketManagerError(
                "The configured ticket category is invalid. Run ticketsetup again."
            )
        bot_member = guild.me
        if bot_member is None and self.bot.user is not None:
            bot_member = guild.get_member(self.bot.user.id)
        if bot_member is None:
            raise TicketManagerError("The bot member is not available in this server.")

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            creator: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
                manage_messages=True,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            ),
        }
        safe_name = re.sub(r"[^a-z0-9-]+", "-", creator.display_name.lower()).strip("-")
        channel = await guild.create_text_channel(
            name=f"ticket-{safe_name or creator.id}"[:90],
            category=category_channel,
            overwrites=overwrites,
            reason=f"AEGIS support ticket opened by {creator.id}",
        )
        try:
            ticket = await self.repository.create_ticket(
                guild_id=guild.id,
                channel_id=channel.id,
                creator_id=creator.id,
                category=category,
            )
        except Exception:
            await channel.delete(reason="Ticket state could not be persisted")
            raise
        await self.log_event(
            ticket=ticket,
            actor=creator,
            event="Opened",
            details=f"Category: {category}",
        )
        return ticket, channel

    async def is_staff(self, ticket: TicketRecord, member: discord.Member) -> bool:
        config = await self.configuration(ticket.guild_id)
        return (
            member.guild_permissions.manage_guild
            or member.guild_permissions.administrator
            or any(role.id == config.staff_role_id for role in member.roles)
        )

    async def can_access(self, ticket: TicketRecord, member: discord.Member) -> bool:
        return member.id == ticket.creator_id or await self.is_staff(ticket, member)

    async def claim(self, ticket: TicketRecord, staff: discord.Member) -> TicketRecord:
        if not await self.is_staff(ticket, staff):
            raise TicketManagerError("Only ticket staff can claim this ticket.")
        claimed = await self.repository.claim_ticket(
            channel_id=ticket.channel_id, staff_id=staff.id
        )
        await self.log_event(
            ticket=claimed,
            actor=staff,
            event="Claimed",
            details="The ticket was claimed by a staff member.",
        )
        return claimed

    async def close(
        self,
        *,
        ticket: TicketRecord,
        channel: discord.TextChannel,
        actor: discord.Member,
    ) -> TicketRecord:
        if ticket.status != "open":
            raise TicketManagerError("This ticket is already closed.")
        if actor.id != ticket.creator_id and not await self.is_staff(ticket, actor):
            raise TicketManagerError("Only the ticket creator or ticket staff can close it.")
        creator = channel.guild.get_member(ticket.creator_id)
        if creator is not None:
            overwrite = channel.overwrites_for(creator)
            overwrite.send_messages = False
            try:
                await channel.set_permissions(
                    creator,
                    overwrite=overwrite,
                    reason=f"AEGIS ticket closed by {actor.id}",
                )
            except discord.HTTPException as exc:
                raise TicketManagerError(
                    "The ticket channel permissions could not be updated; it remains open."
                ) from exc
        closed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            updated = await self.repository.set_ticket_status(
                channel_id=ticket.channel_id,
                status="closed",
                closed_at=closed_at,
            )
        except Exception:
            if creator is not None:
                overwrite.send_messages = True
                try:
                    await channel.set_permissions(creator, overwrite=overwrite)
                except discord.HTTPException:
                    pass
            raise
        try:
            transcript = await self.transcript_bytes(channel)
        except discord.HTTPException:
            transcript = None
        await self.log_event(
            ticket=updated,
            actor=actor,
            event="Closed",
            details=(
                f"Closed by {actor.mention}."
                if transcript is not None
                else f"Closed by {actor.mention}. Transcript fetch was unavailable."
            ),
            transcript=transcript,
        )
        return updated

    async def reopen(
        self,
        *,
        ticket: TicketRecord,
        channel: discord.TextChannel,
        actor: discord.Member,
    ) -> TicketRecord:
        if not await self.is_staff(ticket, actor):
            raise TicketManagerError("Only ticket staff can reopen this ticket.")
        if ticket.status != "closed":
            raise TicketManagerError("This ticket is already open.")
        creator = channel.guild.get_member(ticket.creator_id)
        if creator is not None:
            overwrite = channel.overwrites_for(creator)
            overwrite.view_channel = True
            overwrite.send_messages = True
            overwrite.read_message_history = True
            try:
                await channel.set_permissions(
                    creator,
                    overwrite=overwrite,
                    reason=f"AEGIS ticket reopened by {actor.id}",
                )
            except discord.HTTPException as exc:
                raise TicketManagerError(
                    "The ticket channel permissions could not be updated; it remains closed."
                ) from exc
        updated = await self.repository.set_ticket_status(
            channel_id=ticket.channel_id, status="open", closed_at=None
        )
        await self.log_event(
            ticket=updated,
            actor=actor,
            event="Reopened",
            details="The ticket was reopened by staff.",
        )
        return updated

    async def add_member(
        self,
        *,
        ticket: TicketRecord,
        channel: discord.TextChannel,
        actor: discord.Member,
        member: discord.Member,
    ) -> None:
        if not await self.is_staff(ticket, actor):
            raise TicketManagerError("Only ticket staff can add members.")
        if ticket.status != "open":
            raise TicketManagerError("Members can only be added to open tickets.")
        await channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
            reason=f"AEGIS ticket member added by {actor.id}",
        )
        await self.log_event(
            ticket=ticket,
            actor=actor,
            event="Member added",
            details=f"Added {member.mention} to the ticket.",
        )

    async def remove_member(
        self,
        *,
        ticket: TicketRecord,
        channel: discord.TextChannel,
        actor: discord.Member,
        member: discord.Member,
    ) -> None:
        if not await self.is_staff(ticket, actor):
            raise TicketManagerError("Only ticket staff can remove members.")
        if ticket.status != "open":
            raise TicketManagerError("Members can only be removed from open tickets.")
        config = await self.configuration(ticket.guild_id)
        if member.id == ticket.creator_id or member.id == actor.id:
            raise TicketManagerError("The ticket creator and acting staff member cannot be removed.")
        if any(role.id == config.staff_role_id for role in member.roles):
            raise TicketManagerError("Ticket staff cannot be removed from a ticket.")
        await channel.set_permissions(
            member,
            overwrite=None,
            reason=f"AEGIS ticket member removed by {actor.id}",
        )
        await self.log_event(
            ticket=ticket,
            actor=actor,
            event="Member removed",
            details=f"Removed {member.mention} from the ticket.",
        )

    async def delete(
        self,
        *,
        ticket: TicketRecord,
        channel: discord.TextChannel,
        actor: discord.Member,
    ) -> None:
        if not await self.is_staff(ticket, actor):
            raise TicketManagerError("Only ticket staff can delete a ticket.")
        try:
            await channel.delete(reason=f"AEGIS ticket deleted by {actor.id}")
        except discord.NotFound:
            pass
        except discord.HTTPException as exc:
            raise TicketManagerError(
                "The ticket channel could not be deleted. Its saved record was kept."
            ) from exc

        closed_at = ticket.closed_at or datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        if ticket.status == "open":
            await self.repository.set_ticket_status(
                channel_id=ticket.channel_id,
                status="closed",
                closed_at=closed_at,
            )
        await self.log_event(
            ticket=ticket,
            actor=actor,
            event="Deleted",
            details=f"Ticket channel deleted by {actor.mention}.",
        )

    async def transcript_bytes(self, channel: discord.TextChannel) -> bytes:
        lines = [f"AEGIS ticket transcript for #{channel.name}"]
        async for message in channel.history(limit=1000, oldest_first=True):
            timestamp = message.created_at.astimezone(timezone.utc).isoformat(
                timespec="seconds"
            )
            content = message.clean_content or "[no text content]"
            lines.append(f"[{timestamp}] {message.author.display_name}: {content}")
            for attachment in message.attachments:
                lines.append(f"  Attachment: {attachment.url}")
        return "\n".join(lines).encode("utf-8")

    async def log_event(
        self,
        *,
        ticket: TicketRecord,
        actor: discord.abc.User,
        event: str,
        details: str,
        transcript: bytes | None = None,
    ) -> None:
        await self.repository.log_ticket_event(
            ticket_id=ticket.ticket_id,
            guild_id=ticket.guild_id,
            actor_id=actor.id,
            event=event,
            details=details,
        )
        config = await self.repository.get_ticket_config(ticket.guild_id)
        if config is None or config.log_channel_id is None:
            return
        log_channel = self.bot.get_channel(config.log_channel_id)
        if log_channel is None:
            try:
                log_channel = await self.bot.fetch_channel(config.log_channel_id)
            except discord.HTTPException:
                return
        if not hasattr(log_channel, "send"):
            return
        embed = ticket_event_embed(
            ticket_id=ticket.ticket_id,
            event=event,
            actor=actor,
            details=details,
        )
        try:
            if transcript is None:
                await log_channel.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
                file = discord.File(
                    io.BytesIO(transcript),
                    filename=f"ticket-{ticket.ticket_id}-transcript.txt",
                )
                await log_channel.send(
                    embed=embed,
                    file=file,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except discord.HTTPException:
            return
