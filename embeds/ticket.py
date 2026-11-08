"""Professional green-accented embeds for AEGIS support tickets."""

from __future__ import annotations

from datetime import datetime

import discord

from core.emoji_manager import emoji_markup
from database.repositories.community import TicketRecord


TICKET_COLOR = discord.Color(0x2ECC71)


def ticket_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title=f"{emoji_markup('ticket')} AEGIS SUPPORT CENTER",
        description=(
            "**Make a Ticket Here**\n"
            "Need assistance? Select the appropriate category below. "
            "Our support team will help you."
        ),
        color=TICKET_COLOR,
    )
    embed.set_footer(text="AEGIS Support | Select What's The Issue? to continue")
    return embed


def ticket_welcome_embed(
    ticket: TicketRecord,
    *,
    creator: discord.abc.User,
    created_at: datetime | None = None,
) -> discord.Embed:
    created_at = created_at or datetime.fromisoformat(ticket.created_at)
    timestamp = int(created_at.timestamp())
    embed = discord.Embed(
        title=f"{emoji_markup('ticket')} AEGIS SUPPORT TICKET",
        description=(
            f"**Ticket ID:** `#{ticket.ticket_id}`\n"
            f"**Created by:** {creator.mention}\n"
            f"**Category:** {discord.utils.escape_markdown(ticket.category)}\n"
            f"**Created:** <t:{timestamp}:F>\n\n"
            "A member of the support team will be with you shortly."
        ),
        color=TICKET_COLOR,
    )
    embed.set_footer(text="AEGIS Support | Use the controls below to manage this ticket")
    return embed


def ticket_event_embed(
    *,
    ticket_id: int,
    event: str,
    actor: discord.abc.User,
    details: str,
) -> discord.Embed:
    return discord.Embed(
        title=f"{emoji_markup('ticket')} Ticket #{ticket_id} · {event}",
        description=f"**By:** {actor.mention}\n{details}",
        color=TICKET_COLOR,
    )
