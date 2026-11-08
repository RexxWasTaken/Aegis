"""Shared usage and permission error embeds for moderation previews."""

from __future__ import annotations

import discord

from core.emoji_manager import emoji_for
from embeds.moderation import COMMAND_SPECS, ERROR_COLOR


def wrong_usage_embed(
    command_name: str, *, guild: discord.Guild | None = None
) -> discord.Embed:
    """Build a usage error for a registered moderation command."""
    try:
        usage = COMMAND_SPECS[command_name].usage
    except KeyError as exc:
        raise ValueError(f"Unknown moderation command: {command_name}") from exc
    return discord.Embed(
        title=f"{emoji_for('wrong', guild)} Wrong usage",
        description=f"**Usage**\n{usage}",
        color=ERROR_COLOR,
    )


def missing_permissions_embed(
    command_name: str, *, guild: discord.Guild | None = None
) -> discord.Embed:
    """Build the standard permission error, validating the command name."""
    if command_name not in COMMAND_SPECS:
        raise ValueError(f"Unknown moderation command: {command_name}")
    return discord.Embed(
        title=f"{emoji_for('error', guild)} Missing permissions",
        description="You need the required permissions to execute this command.",
        color=ERROR_COLOR,
    )


def operation_error_embed(
    message: str, *, guild: discord.Guild | None = None
) -> discord.Embed:
    """Build a concise error response without exposing internal exceptions."""
    safe_message = discord.utils.escape_mentions(message)
    return discord.Embed(
        title=f"{emoji_for('error', guild)} Action failed",
        description=safe_message,
        color=ERROR_COLOR,
    )
