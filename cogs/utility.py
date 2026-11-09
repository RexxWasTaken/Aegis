"""Prefix configuration and small AEGIS utility commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.configuration import get_invite_url, get_support_url
from database.repositories.community import CommunityRepository


def _repository(bot: commands.Bot) -> CommunityRepository:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The AEGIS database is not initialized.")
    return repository


class ExternalLinkView(discord.ui.View):
    def __init__(self, *, label: str, url: str) -> None:
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.link,
                url=url,
            )
        )


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="prefix",
        description="Show the prefix AEGIS uses in this server.",
    )
    async def prefix(self, ctx: commands.Context) -> None:
        """Show the actual saved guild prefix, or the configured default in DMs."""
        guild_id = ctx.guild.id if ctx.guild is not None else None
        prefix = await self.bot.get_guild_prefix(guild_id)
        await ctx.send(
            f"Hey! My prefix here is `{prefix}`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="setprefix",
        description="Set this server's custom AEGIS prefix.",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(prefix="A 1–16 character prefix without spaces.")
    async def setprefix(self, ctx: commands.Context, *, prefix: str) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            saved = await _repository(self.bot).set_guild_prefix(
                guild_id=ctx.guild.id,
                prefix=prefix,
            )
        except ValueError as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            f"This server's AEGIS prefix is now `{saved}`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="ping",
        description="Check AEGIS gateway latency.",
    )
    async def ping(self, ctx: commands.Context) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await ctx.send(
            f"AEGIS gateway latency: `{latency_ms} ms`.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="support",
        description="Open the configured AEGIS support link, if one is set.",
    )
    async def support(self, ctx: commands.Context) -> None:
        url = get_support_url()
        if url is None:
            await ctx.send("AEGIS support link has not been configured yet.")
            return
        await ctx.send(
            "AEGIS support:",
            view=ExternalLinkView(label="AEGIS Support", url=url),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="invite",
        description="Open the configured AEGIS invite link, if one is set.",
    )
    async def invite(self, ctx: commands.Context) -> None:
        url = get_invite_url()
        if url is None:
            await ctx.send("AEGIS invite link has not been configured yet.")
            return
        await ctx.send(
            "Invite AEGIS:",
            view=ExternalLinkView(label="Invite AEGIS", url=url),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
