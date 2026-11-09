"""User and server information commands."""

from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands


def _timestamp(value: datetime | None) -> str:
    if value is None:
        return "Not available"
    normalized = (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
    return f"<t:{int(normalized.timestamp())}:F>"


class InformationCog(commands.Cog):
    @commands.hybrid_command(
        name="userinfo",
        description="Show a user's public Discord account information.",
    )
    @app_commands.describe(user="The user to inspect; defaults to you.")
    async def userinfo(
        self,
        ctx: commands.Context,
        user: discord.User | None = None,
    ) -> None:
        target = user or ctx.author
        embed = discord.Embed(
            title=f"User information • {str(target)[:180]}",
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="User ID", value=str(target.id), inline=True)
        embed.add_field(
            name="Account created",
            value=_timestamp(target.created_at),
            inline=False,
        )
        joined_at = getattr(target, "joined_at", None)
        if joined_at is not None:
            embed.add_field(
                name="Joined this server",
                value=_timestamp(joined_at),
                inline=False,
            )
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="serverinfo",
        description="Show information about this server.",
    )
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        if guild is None:
            raise commands.NoPrivateMessage()
        embed = discord.Embed(
            title=f"Server information • {guild.name[:180]}",
            color=discord.Color.blurple(),
        )
        if guild.icon is not None:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Server ID", value=str(guild.id), inline=True)
        embed.add_field(
            name="Members",
            value=str(guild.member_count or 0),
            inline=True,
        )
        embed.add_field(name="Owner", value=f"<@{guild.owner_id}>", inline=True)
        embed.add_field(
            name="Created",
            value=_timestamp(guild.created_at),
            inline=False,
        )
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="avatar",
        description="Show a user's profile picture.",
    )
    @app_commands.describe(user="The user whose profile picture to show.")
    async def avatar(
        self,
        ctx: commands.Context,
        user: discord.User | None = None,
    ) -> None:
        target = user or ctx.author
        embed = discord.Embed(
            title=f"{str(target)[:180]}'s avatar",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=target.display_avatar.url)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InformationCog())
