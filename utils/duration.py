"""Bounded duration parsing for moderation actions."""

from __future__ import annotations

import re
from datetime import timedelta


_DURATION_PATTERN = re.compile(r"^([1-9]\d*)([smhdw])$", re.IGNORECASE)
_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 60 * 60,
    "d": 60 * 60 * 24,
    "w": 60 * 60 * 24 * 7,
}
MAX_DURATION_SECONDS = 365 * 24 * 60 * 60


def parse_duration(value: str) -> timedelta:
    """Parse a single positive s/m/h/d/w duration, capped at one year."""
    match = _DURATION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("Use a duration such as 30s, 10m, 2h, 7d, or 1w.")
    amount = int(match.group(1))
    seconds = amount * _UNIT_SECONDS[match.group(2).lower()]
    if seconds > MAX_DURATION_SECONDS:
        raise ValueError("The duration cannot exceed 365 days.")
    return timedelta(seconds=seconds)


def format_duration(value: timedelta) -> str:
    """Format a positive duration in the largest exact whole unit."""
    seconds = int(value.total_seconds())
    if seconds <= 0:
        raise ValueError("The duration must be greater than zero.")
    for unit, unit_seconds in (
        ("week", 7 * 24 * 60 * 60),
        ("day", 24 * 60 * 60),
        ("hour", 60 * 60),
        ("minute", 60),
        ("second", 1),
    ):
        if seconds % unit_seconds == 0:
            amount = seconds // unit_seconds
            return f"{amount} {unit}{'' if amount == 1 else 's'}"
    raise AssertionError("Duration formatting reached an unreachable state.")
