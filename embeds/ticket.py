"""Green-accented embeds for the AEGIS ticket workflow."""

from __future__ import annotations

from datetime import datetime, timezone

import discord

from core.emoji_manager import emoji_markup
from database.repositories.community import TicketRecord


TICKET_COLOR = discord.Color(0x2ECC71)


def _timestamp(value: str | None) -> int | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def ticket_panel_embed() -> discord.Embed:
    return discord.Embed(
        description=(
            "Make Ticket For Complains Here\n\n"
            "To create a ticket, select an issue from the dropdown below.\n\n"
            f"{emoji_markup('ticket')} AEGIS Support"
        ),
        color=TICKET_COLOR,
    )


def ticket_welcome_embed(
    ticket: TicketRecord,
    *,
    creator: discord.abc.User,
    created_at: datetime | None = None,
) -> discord.Embed:
    created_at = created_at or datetime.fromisoformat(ticket.created_at)
    timestamp = int(created_at.timestamp())
    embed = discord.Embed(
        title=f"{emoji_markup('ticket')} AEGIS Support Ticket",
        description=(
            f"Ticket ID: `#{ticket.ticket_id}`\n"
            f"Created by: {creator.mention}\n"
            f"Issue: {discord.utils.escape_markdown(ticket.category)}\n"
            f"Created: <t:{timestamp}:F>\n\n"
            "A member of the support team will be with you shortly."
        ),
        color=TICKET_COLOR,
    )
    embed.set_footer(text="AEGIS Support")
    return embed


def ticket_status_embed(
    ticket: TicketRecord,
    *,
    actor: discord.abc.User,
    status: str,
) -> discord.Embed:
    status_text = "closed" if status == "closed" else "reopened"
    embed = discord.Embed(
        title=f"{emoji_markup('ticket')} Ticket #{ticket.ticket_id} {status_text}",
        description=f"Updated by {actor.mention}",
        color=TICKET_COLOR,
    )
    embed.set_footer(text="AEGIS Support")
    return embed


def ticket_info_embed(
    ticket: TicketRecord,
    *,
    creator_name: str,
    claimed_name: str | None,
) -> discord.Embed:
    fields = [
        ("Status", ticket.status.title()),
        ("Issue", discord.utils.escape_markdown(ticket.category)),
        ("Created by", creator_name),
        ("Claimed by", claimed_name or "Unclaimed"),
    ]
    created = _timestamp(ticket.created_at)
    if created is not None:
        fields.append(("Created", f"<t:{created}:F>"))
    closed = _timestamp(ticket.closed_at)
    if closed is not None:
        fields.append(("Closed", f"<t:{closed}:F>"))
    embed = discord.Embed(
        title=f"{emoji_markup('ticket')} Ticket #{ticket.ticket_id}",
        color=TICKET_COLOR,
    )
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=True)
    embed.set_footer(text="AEGIS Support")
    return embed


def ticket_transcript_embed(
    ticket: TicketRecord,
    *,
    actor: discord.abc.User,
) -> discord.Embed:
    return discord.Embed(
        title=f"{emoji_markup('ticket')} Ticket #{ticket.ticket_id} Transcript",
        description=f"Transcript requested by {actor.mention}.",
        color=TICKET_COLOR,
    )


def ticket_delete_confirmation_embed(ticket: TicketRecord) -> discord.Embed:
    return discord.Embed(
        title=f"{emoji_markup('warning')} Delete ticket #{ticket.ticket_id}?",
        description=(
            "Confirming permanently deletes this ticket channel. "
            "The saved ticket record, event history, and transcript will remain. "
            "A transcript copy will be sent to the confirming staff member."
        ),
        color=TICKET_COLOR,
    )


def ticket_event_embed(
    *,
    ticket_id: int,
    event: str,
    actor: discord.abc.User,
    details: str,
) -> discord.Embed:
    return discord.Embed(
        title=f"{emoji_markup('ticket')} Ticket #{ticket_id}: {event}",
        description=f"By {actor.mention}\n{details}",
        color=TICKET_COLOR,
    )
