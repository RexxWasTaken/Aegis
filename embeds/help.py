"""Dark, metadata-driven embeds for the AEGIS interactive Help experience."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import discord

from core.emoji_manager import emoji_markup


HELP_COLOR = discord.Color(0x2B2D31)
_CATEGORY_EMOJIS = {
    "Automod": "antinuke",
    "Moderation": "moderation",
    "Welcome": "welcomer",
    "Music": "music",
    "Ticket": "ticket",
    "Giveaway": "giveaway",
    "Security": "security",
    "Utility": "utility",
    "AI": "ai",
    "Owner": "owner",
}


def _limited(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _category_heading(category: str) -> str:
    emoji_name = _CATEGORY_EMOJIS.get(category)
    return f"{emoji_markup(emoji_name)} {category}" if emoji_name else category


def help_front_page(categories: Sequence[str]) -> discord.Embed:
    """Build the exact Help home copy and only list registered categories."""
    embed = discord.Embed(
        title="Welcome to AEGIS!",
        description=(
            "Your ultimate versatile Discord bot.\n"
            "Use the dropdown menus below to explore command categories."
        ),
        color=HELP_COLOR,
    )
    category_lines = [_category_heading(category) for category in categories]
    if category_lines:
        embed.add_field(
            name="Categories",
            value="\n".join(category_lines),
            inline=False,
        )
    return embed


def help_category_page(
    *,
    category: str,
    mode: str,
    entries: Sequence[Any],
    page: int,
    page_count: int,
) -> discord.Embed:
    """Build a compact page with actual command names and discovered metadata."""
    embed = discord.Embed(
        title=f"{_category_heading(category)} {category.upper()} COMMANDS",
        description=f"{mode.title()} commands",
        color=HELP_COLOR,
    )
    for entry in entries:
        aliases = ", ".join(f"`{alias}`" for alias in entry.aliases) or "None"
        permissions = ", ".join(entry.permissions) or "None documented"
        examples = "\n".join(f"`{example}`" for example in entry.examples)
        if not examples:
            examples = "No verified examples are documented."
        value = (
            f"Aliases: {aliases}\n"
            f"Usage: `{entry.usage}`\n"
            f"Description: {entry.description}\n"
            f"Required permissions: {permissions}\n"
            f"Verified examples: {examples}"
        )
        embed.add_field(
            name=_limited(entry.qualified_name, 256),
            value=_limited(value, 1024),
            inline=False,
        )
    if not entries:
        embed.description = f"No registered {mode} commands are available here."
    embed.set_footer(text=f"Page {page} of {page_count}")
    return embed


def help_command_details(info: Any) -> discord.Embed:
    """Display the verified metadata for a prefix name, alias, or slash command."""
    aliases = ", ".join(f"`{alias}`" for alias in info.aliases) or "None"
    permissions = ", ".join(info.permissions) or "None documented"
    examples = "\n".join(f"`{example}`" for example in info.examples)
    if not examples:
        examples = "No verified examples are documented."
    embed = discord.Embed(
        title=f"{_category_heading(info.category)} command details",
        description=info.description,
        color=HELP_COLOR,
    )
    embed.add_field(name="Command", value=_limited(info.qualified_name, 1024), inline=False)
    embed.add_field(name="Usage", value=_limited(info.usage, 1024), inline=False)
    embed.add_field(name="Aliases", value=_limited(aliases, 1024), inline=False)
    embed.add_field(
        name="Required permissions",
        value=_limited(permissions, 1024),
        inline=False,
    )
    embed.add_field(name="Verified examples", value=_limited(examples, 1024), inline=False)
    embed.add_field(name="Category", value=_category_heading(info.category), inline=False)
    return embed
