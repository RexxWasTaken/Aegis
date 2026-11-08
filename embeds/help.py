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
    category_lines = [
        _limited(_category_heading(category), 100)
        for category in categories[:25]
    ]
    category_fields: list[list[str]] = []
    current_field: list[str] = []
    current_length = 0
    for line in category_lines:
        line_length = len(line) + (1 if current_field else 0)
        if current_field and current_length + line_length > 1024:
            category_fields.append(current_field)
            current_field = []
            current_length = 0
            line_length = len(line)
        current_field.append(line)
        current_length += line_length
    if current_field:
        category_fields.append(current_field)

    for index, lines in enumerate(category_fields):
        embed.add_field(
            name="Categories" if index == 0 else f"Categories ({index + 1})",
            value="\n".join(lines),
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
        title=_limited(
            f"{_category_heading(category)} {category.upper()} COMMANDS",
            256,
        ),
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
            value=_limited(value, 800),
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
        title=_limited(f"{_category_heading(info.category)} command details", 256),
        description=_limited(info.description, 1024),
        color=HELP_COLOR,
    )
    embed.add_field(name="Command", value=_limited(info.qualified_name, 256), inline=False)
    embed.add_field(name="Usage", value=_limited(info.usage, 512), inline=False)
    embed.add_field(name="Aliases", value=_limited(aliases, 512), inline=False)
    embed.add_field(
        name="Required permissions",
        value=_limited(permissions, 512),
        inline=False,
    )
    embed.add_field(name="Verified examples", value=_limited(examples, 1024), inline=False)
    embed.add_field(
        name="Category",
        value=_limited(_category_heading(info.category), 256),
        inline=False,
    )
    return embed
