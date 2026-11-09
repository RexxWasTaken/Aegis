"""Guild-local queue helpers built on Wavelink's native queue."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import wavelink


QUEUE_PAGE_SIZE = 10
REPEAT_MODES = {
    "off": wavelink.QueueMode.normal,
    "track": wavelink.QueueMode.loop,
    "queue": wavelink.QueueMode.loop_all,
}


@dataclass(frozen=True)
class QueuePage:
    tracks: tuple[wavelink.Playable, ...]
    page: int
    page_count: int
    total: int


def build_queue_page(
    queue: wavelink.Queue,
    page: int = 1,
    *,
    page_size: int = QUEUE_PAGE_SIZE,
) -> QueuePage:
    """Return a clamped, immutable slice of the upcoming queue."""
    if page_size < 1:
        raise ValueError("page_size must be positive")

    tracks = tuple(queue)
    page_count = max(1, (len(tracks) + page_size - 1) // page_size)
    safe_page = min(max(page, 1), page_count)
    start = (safe_page - 1) * page_size
    return QueuePage(
        tracks=tracks[start : start + page_size],
        page=safe_page,
        page_count=page_count,
        total=len(tracks),
    )


def set_repeat_mode(player: Any, mode: str) -> str:
    """Apply one of the supported Wavelink loop modes."""
    normalized = mode.casefold().strip()
    try:
        player.queue.mode = REPEAT_MODES[normalized]
    except KeyError as exc:
        raise ValueError("Choose one of: off, track, or queue.") from exc
    return normalized


def shuffle_queue(player: Any) -> int:
    """Shuffle only upcoming tracks, leaving the playing track untouched."""
    count = len(player.queue)
    player.queue.shuffle()
    return count


def previous_track(player: Any) -> wavelink.Playable | None:
    """Return the previous history entry without changing queue state."""
    history = getattr(player.queue, "history", None)
    if history is None or len(history) < 2:
        return None
    return history[-2]


async def play_previous(player: Any) -> wavelink.Playable | None:
    """Play the prior history entry and put the interrupted track back first."""
    track = previous_track(player)
    if track is None:
        return None

    current = player.current
    if current is not None:
        player.queue.put_at(0, current)
    await player.play(track, add_history=False)
    return track
