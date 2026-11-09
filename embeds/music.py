"""Compact dark-blue music embeds for the AEGIS Discord player."""

from __future__ import annotations

from typing import Any

import discord

from core.emoji_manager import emoji_markup
from utils.music_helpers import format_duration, progress_bar


MUSIC_BLUE = discord.Color(0x12A8FF)


def _track_requester(track: Any) -> str:
    try:
        requester_id = dict(track.extras).get("requester_id")
    except (AttributeError, TypeError, ValueError):
        requester_id = None
    return f"<@{requester_id}>" if requester_id else "Unknown"


def player_embed(player: Any, track: Any | None = None) -> discord.Embed:
    """Build a live player panel with the cover art, requester, and progress."""
    current = track or getattr(player, "current", None)
    if current is None:
        return discord.Embed(
            title="AEGIS Music",
            description="Nothing is playing right now.",
            color=MUSIC_BLUE,
        )

    length = int(getattr(current, "length", 0) or 0)
    position = int(getattr(player, "position", 0) or 0)
    is_stream = bool(getattr(current, "is_stream", False))
    duration = "LIVE" if is_stream else format_duration(length)
    progress = "LIVE" if is_stream else (
        f"{progress_bar(position, length)}  {format_duration(position)} / {duration}"
    )

    embed = discord.Embed(
        title=str(getattr(current, "title", "Unknown track"))[:256],
        url=getattr(current, "uri", None),
        description=f"**{str(getattr(current, 'author', 'Unknown artist'))[:256]}**",
        color=MUSIC_BLUE,
    )
    embed.add_field(
        name=f"{emoji_markup('media')} Playback",
        value=progress[:1024],
        inline=False,
    )
    embed.add_field(
        name="Requested by",
        value=_track_requester(current),
        inline=True,
    )

    queue = getattr(player, "queue", None)
    embed.add_field(
        name=f"{emoji_markup('queue')} Up next",
        value=f"{len(queue) if queue is not None else 0} track(s)",
        inline=True,
    )

    if getattr(current, "artwork", None):
        embed.set_thumbnail(url=current.artwork)

    loop_mode = getattr(getattr(queue, "mode", None), "name", "normal")
    loop_label = {
        "normal": "Off",
        "loop": "Track",
        "loop_all": "Queue",
    }.get(loop_mode, "Off")
    autoplay = "On" if getattr(player, "autoplay", None) == getattr(
        __import__("wavelink"), "AutoPlayMode"
    ).enabled else "Off"
    embed.set_footer(text=f"Loop: {loop_label}  |  Autoplay: {autoplay}")
    return embed


def queue_embed(
    page_tracks: tuple[Any, ...],
    *,
    page: int,
    page_count: int,
    total: int,
) -> discord.Embed:
    """Render one page of upcoming tracks without overflowing Discord limits."""
    embed = discord.Embed(
        title=f"{emoji_markup('queue')} AEGIS Queue",
        color=MUSIC_BLUE,
    )
    if not total:
        embed.description = "The queue is empty."
    else:
        rows = []
        offset = (page - 1) * 10
        for index, track in enumerate(page_tracks, start=offset + 1):
            title = str(getattr(track, "title", "Unknown track")).replace("\n", " ")[:120]
            artist = str(getattr(track, "author", "Unknown artist")).replace("\n", " ")[:80]
            rows.append(f"`{index}.` **{title}** — {artist}")
        embed.description = "\n".join(rows)[:4000]
    embed.set_footer(text=f"{total} upcoming track(s)  |  Page {page} of {page_count}")
    return embed


def lyrics_embed(track: Any, lyrics: str) -> discord.Embed:
    """Render the fetched lyrics within Discord's embed character budget."""
    title = str(getattr(track, "title", "Lyrics"))[:200]
    author = str(getattr(track, "author", ""))[:200]
    body = lyrics.strip()
    if len(body) > 3900:
        body = body[:3880].rsplit("\n", 1)[0] + "\n\n[lyrics shortened]"
    embed = discord.Embed(
        title=f"Lyrics: {title}",
        description=body or "No lyrics were found.",
        color=MUSIC_BLUE,
    )
    if author:
        embed.set_author(name=author)
    return embed
