"""Small, testable helpers shared by music commands and embeds."""

from __future__ import annotations

import re
from typing import Any

import aiohttp


_TIMESTAMP = re.compile(r"^\d+(?::[0-5]?\d){0,2}$")
_SYNCED_LYRIC_TIMESTAMP = re.compile(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]")
LYRICS_URL = "https://lrclib.net/api/get"


def format_duration(milliseconds: int) -> str:
    """Format a non-negative millisecond duration as M:SS or H:MM:SS."""
    total_seconds = max(0, int(milliseconds)) // 1000
    seconds = total_seconds % 60
    minutes = (total_seconds // 60) % 60
    hours = total_seconds // 3600
    return (
        f"{hours}:{minutes:02}:{seconds:02}"
        if hours
        else f"{total_seconds // 60}:{seconds:02}"
    )


def progress_bar(position_ms: int, duration_ms: int, *, width: int = 16) -> str:
    """Return an ASCII progress bar that is safe in Discord embeds."""
    if width < 1:
        raise ValueError("width must be positive")
    if duration_ms <= 0:
        return "[" + "-" * width + "]"
    ratio = min(max(position_ms, 0) / duration_ms, 1.0)
    filled = min(width, int(ratio * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def parse_seek_position(value: str, *, duration_ms: int | None = None) -> int:
    """Parse an integer-second, MM:SS, or HH:MM:SS seek target."""
    normalized = value.strip()
    if not _TIMESTAMP.fullmatch(normalized):
        raise ValueError("Use seconds, MM:SS, or HH:MM:SS for the seek position.")
    parts = [int(part) for part in normalized.split(":")]
    if len(parts) == 1:
        seconds = parts[0]
    elif len(parts) == 2:
        seconds = parts[0] * 60 + parts[1]
    else:
        seconds = parts[0] * 3600 + parts[1] * 60 + parts[2]

    position_ms = seconds * 1000
    if duration_ms is not None and duration_ms > 0 and position_ms >= duration_ms:
        raise ValueError("The seek position must be before the track ends.")
    return position_ms


def requester_id(track: Any) -> int | None:
    """Read the requester id stored in a Wavelink track's extras."""
    try:
        value = dict(track.extras).get("requester_id")
        return int(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


async def fetch_lyrics(track: Any) -> str | None:
    """Look up lyrics by title and artist using LRCLIB without blocking Discord."""
    title = str(getattr(track, "title", "")).strip()
    artist = str(getattr(track, "author", "")).strip()
    if not title:
        return None

    params: dict[str, str] = {
        "track_name": title[:250],
        "artist_name": artist[:250],
    }
    length_ms = int(getattr(track, "length", 0) or 0)
    if length_ms > 0:
        params["duration"] = str(max(1, round(length_ms / 1000)))

    timeout = aiohttp.ClientTimeout(total=8)
    headers = {"User-Agent": "AEGIS-Discord-Bot/1.0 (music lyrics lookup)"}
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(LYRICS_URL, params=params) as response:
                if response.status == 404:
                    return None
                response.raise_for_status()
                data = await response.json(content_type=None)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None

    plain = data.get("plainLyrics")
    if isinstance(plain, str) and plain.strip():
        return plain.strip()

    synced = data.get("syncedLyrics")
    if isinstance(synced, str) and synced.strip():
        without_timestamps = _SYNCED_LYRIC_TIMESTAMP.sub("", synced)
        lines = [line.strip() for line in without_timestamps.splitlines() if line.strip()]
        return "\n".join(lines) or None
    return None
