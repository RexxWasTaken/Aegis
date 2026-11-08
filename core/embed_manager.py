"""Shared, compact embed factory for AEGIS bot responses."""

from __future__ import annotations

import re
from collections.abc import Iterable

import discord

from core.emoji_manager import emoji_markup


_USER_MENTION = re.compile(r"(?<!\*)<@!?\d+>(?!\*)")
_MESSAGE_COUNT = re.compile(r"\b(\d+\s+(?:(?:bot|human)\s+)?messages?)\b", re.IGNORECASE)


class EmbedManager:
    """Build consistent Discord embeds using only configured custom emojis."""

    @staticmethod
    def _emoji_prefix(emoji_names: Iterable[str]) -> str:
        return " ".join(markup for name in emoji_names if (markup := emoji_markup(name)))

    @staticmethod
    def _bold_mentions(text: str) -> str:
        return _USER_MENTION.sub(lambda match: f"**{match.group(0)}**", text)

    @staticmethod
    def _details_text(details: str | None) -> str:
        if not details:
            return ""
        lines = []
        for line in details.strip().splitlines():
            lines.append(line[2:] if line.startswith("> ") else line)
        return "\n".join(lines).strip()

    def action(
        self,
        *,
        message: str,
        details: str | None = None,
        emoji_names: Iterable[str] = (),
        color: discord.Color,
    ) -> discord.Embed:
        """Return a compact action embed with its icon and message on one line."""
        message = _MESSAGE_COUNT.sub(lambda match: f"**{match.group(1)}**", message)
        message = self._bold_mentions(message)
        prefix = self._emoji_prefix(emoji_names)
        first_line = f"{prefix} {message}".strip()
        detail_text = self._bold_mentions(self._details_text(details))
        description = "\n".join(part for part in (first_line, detail_text) if part)
        return discord.Embed(description=description or None, color=color)

    def titled(
        self,
        *,
        title: str,
        description: str | None = None,
        emoji_names: Iterable[str] = (),
        color: discord.Color,
    ) -> discord.Embed:
        """Return a titled embed for paginated or informational views."""
        prefix = self._emoji_prefix(emoji_names)
        title = self._bold_mentions(title)
        if prefix:
            title = f"{prefix} {title}"
        if description:
            description = self._bold_mentions(description)
        return discord.Embed(title=title, description=description or None, color=color)


embed_manager = EmbedManager()
