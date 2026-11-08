"""AEGIS-branded embeds for the interactive command help experience."""

from __future__ import annotations

from collections.abc import Sequence

import discord

from core.emoji_manager import emoji_markup


HELP_COLOR = discord.Color(0x2ECC71)


def help_front_page(
    *,
    prefix_count: int,
    slash_count: int,
    category_counts: dict[str, int],
) -> discord.Embed:
    """Build the Help home page, keeping Ticket and Giveaway prominent."""
    embed = discord.Embed(
        title="AEGIS Help Center",
        description=(
            "Choose a category and command type from the menus below.\n"
            f"{emoji_markup('ticket')} **Ticket** — private support and ticket management\n"
            f"{emoji_markup('giveaway')} **Giveaway** — reaction-entry giveaways"
        ),
        color=HELP_COLOR,
    )
    embed.add_field(
        name="Command types",
        value=f"Prefix commands: {prefix_count}\nSlash commands: {slash_count}",
        inline=False,
    )
    other_categories = [
        f"{emoji_markup('moderation')} **{name}** — {count} commands"
        for name, count in sorted(category_counts.items())
        if name not in {"Ticket", "Giveaway"}
    ]
    if other_categories:
        embed.add_field(name="More categories", value="\n".join(other_categories), inline=False)
    embed.set_footer(text="AEGIS | Select a category to browse commands")
    return embed


def help_category_page(
    *,
    category: str,
    mode: str,
    entries: Sequence[tuple[str, str]],
    page: int,
    page_count: int,
) -> discord.Embed:
    """Build one page from commands discovered from the live bot registries."""
    emoji_name = {
        "Ticket": "ticket",
        "Giveaway": "giveaway",
        "Moderation": "moderation",
    }.get(category, "folder")
    embed = discord.Embed(
        title=f"{emoji_markup(emoji_name)} {category} Commands",
        description=f"Showing registered {mode} commands.",
        color=HELP_COLOR,
    )
    if entries:
        for name, description in entries:
            embed.add_field(
                name=f"`{name}`",
                value=description or "No description provided.",
                inline=False,
            )
    else:
        embed.add_field(
            name="No commands available",
            value=f"There are no registered {mode} commands in this category yet.",
            inline=False,
        )
    embed.set_footer(text=f"Page {page} of {page_count} | AEGIS Help Center")
    return embed
