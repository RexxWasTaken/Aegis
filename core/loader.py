"""AEGIS moderation, community, and music extension loading."""

from __future__ import annotations

from discord.ext import commands


MODERATION_EXTENSIONS = (
    "cogs.moderation.bans",
    "cogs.moderation.kicks",
    "cogs.moderation.timeouts",
    "cogs.moderation.voice_moderation",
    "cogs.moderation.warnings",
    "cogs.moderation.purge",
    "cogs.moderation.channels",
    "cogs.moderation.nicknames",
    "cogs.moderation.jail",
)

COMMUNITY_EXTENSIONS = (
    "cogs.ticket",
    "cogs.giveaway",
    "cogs.help",
    "cogs.owner",
    "cogs.music.commands",
    "cogs.utility",
    "cogs.information",
    "cogs.fun",
    "cogs.voice",
    "cogs.games",
    "cogs.security",
    "cogs.welcome",
    "cogs.reaction_roles",
    "cogs.logging",
)


async def load_extensions(bot: commands.Bot) -> None:
    for extension in (*MODERATION_EXTENSIONS, *COMMUNITY_EXTENSIONS):
        await bot.load_extension(extension)
