"""Custom-emoji-only embeds for AEGIS reaction-entry giveaways."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from collections.abc import Sequence

import discord

from core.emoji_manager import emoji_markup
from database.repositories.community import GiveawayRecord
from utils.duration import format_duration


GIVEAWAY_COLOR = discord.Color(0x2ECC71)


def giveaway_announcement(
    *,
    prize: str,
    winner_count: int,
    host: discord.abc.User | int,
    ends_at: datetime,
    paused_seconds: int | None = None,
) -> discord.Embed:
    end_timestamp = int(ends_at.astimezone(timezone.utc).timestamp())
    arrow = emoji_markup("arrow")
    host_mention = getattr(host, "mention", f"<@{host}>")
    end_line = (
        f"{arrow} Ends: Paused\n"
        f"{arrow} Remaining: {format_duration(timedelta(seconds=max(1, paused_seconds or 1)))}"
        if paused_seconds is not None
        else f"{arrow} Ends: <t:{end_timestamp}:F> (<t:{end_timestamp}:R>)"
    )
    embed = discord.Embed(
        title=f"{emoji_markup('giveaway')} NEW GIVEAWAY",
        description=(
            f"**{discord.utils.escape_markdown(prize)}**\n\n"
            f"{arrow} Winners: {winner_count}\n"
            f"{arrow} Hosted by: {host_mention}\n"
            f"{end_line}\n\n"
            f"React with {emoji_markup('giveaway')} to enter!"
        ),
        color=GIVEAWAY_COLOR,
    )
    footer = (
        "AEGIS Giveaway | Paused"
        if paused_seconds is not None
        else "AEGIS Giveaway | Entries are counted from the live reaction"
    )
    embed.set_footer(text=footer)
    return embed


def giveaway_ended_embed(
    giveaway: GiveawayRecord,
    *,
    winners: Sequence[int],
    reroll: bool = False,
) -> discord.Embed:
    if winners:
        winner_text = "\n".join(
            f"{emoji_markup('success')} <@{winner_id}>" for winner_id in winners
        )
        heading = "New winners" if reroll else "Congratulations!"
    else:
        winner_text = "No eligible participants entered." if not reroll else (
            "No new eligible participants are available for a reroll."
        )
        heading = "Giveaway ended" if not reroll else "Reroll unavailable"
    embed = discord.Embed(
        title=f"{emoji_markup('giveaway')} GIVEAWAY ENDED",
        description=(
            f"{heading}\n\n"
            f"{winner_text}\n\n"
            f"{emoji_markup('giveaway')} Prize: "
            f"{discord.utils.escape_markdown(giveaway.prize)}"
        ),
        color=GIVEAWAY_COLOR,
    )
    return embed


def giveaway_list_embed(records: Sequence[GiveawayRecord]) -> discord.Embed:
    embed = discord.Embed(
        title=f"{emoji_markup('giveaway')} Active Giveaways",
        color=GIVEAWAY_COLOR,
    )
    if not records:
        embed.description = "There are no active or paused giveaways."
        return embed
    lines = []
    for record in records:
        state = "Paused" if record.status == "paused" else "Active"
        lines.append(
            f"`{record.message_id}` — **{discord.utils.escape_markdown(record.prize)}** "
            f"({state}, {record.winner_count} winner(s))"
        )
    embed.description = "\n".join(lines)
    return embed
