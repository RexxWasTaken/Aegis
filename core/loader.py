"""Moderation extension loading."""

from __future__ import annotations

from discord.ext import commands


MODERATION_EXTENSIONS = ("cogs.moderation.bans", "cogs.moderation.kicks")


async def load_extensions(bot: commands.Bot) -> None:
    for extension in MODERATION_EXTENSIONS:
        await bot.load_extension(extension)
