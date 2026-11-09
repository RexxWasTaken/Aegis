"""User, server, role, channel, bot, and invite information commands."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands


_CHANNEL_MENTION = re.compile(r"<#(\d{15,20})>")


def _timestamp(value: object | None) -> str:
    if value is None or not hasattr(value, "timestamp"):
        return "Unknown"
    return f"<t:{int(value.timestamp())}:F>"


def resolve_channel(guild: discord.Guild, query: str) -> discord.abc.GuildChannel | None:
    """Resolve a cached channel by mention, ID, or exact name."""
    value = query.strip()
    mention = _CHANNEL_MENTION.fullmatch(value)
    channel_id = int(mention.group(1)) if mention else int(value) if value.isdecimal() else None
    if channel_id is not None:
        return guild.get_channel(channel_id)
    normalized = value.removeprefix("#").casefold()
    return next(
        (
            channel
            for channel in guild.channels
            if channel.name.casefold() == normalized
        ),
        None,
    )


class InformationCog(commands.Cog):
    """Build metadata-driven embeds from Discord's current objects."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="userinfo",
        description="Show a user's Discord account and server details.",
    )
    @app_commands.describe(user="The user to inspect; defaults to you.")
    async def userinfo(
        self,
        ctx: commands.Context,
        user: discord.User | None = None,
    ) -> None:
        target = user or ctx.author
        display_name = getattr(target, "display_name", target.name)
        embed = discord.Embed(
            title=f"User information: {display_name}",
            description=f"{target.mention}\n`{target}` • ID `{target.id}`",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Account created", value=_timestamp(target.created_at))
        embed.add_field(name="Bot account", value="Yes" if target.bot else "No")
        if isinstance(target, discord.Member):
            embed.add_field(name="Joined this server", value=_timestamp(target.joined_at))
            roles = [role.mention for role in target.roles if not role.is_default()]
            role_text = ", ".join(roles[-10:]) if roles else "No assigned roles"
            embed.add_field(name="Roles", value=role_text[:1000], inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="avatar",
        description="Show a user's current Discord avatar.",
    )
    @app_commands.describe(user="The user whose avatar you want to see.")
    async def avatar(
        self,
        ctx: commands.Context,
        user: discord.User | None = None,
    ) -> None:
        target = user or ctx.author
        embed = discord.Embed(
            title=f"{getattr(target, 'display_name', target.name)}'s avatar",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=target.display_avatar.url)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="banner",
        description="Show a user's profile banner when one is available.",
    )
    @app_commands.describe(user="The user whose banner you want to see.")
    async def banner(
        self,
        ctx: commands.Context,
        user: discord.User | None = None,
    ) -> None:
        target = user or ctx.author
        try:
            full_user = await self.bot.fetch_user(target.id)
        except discord.HTTPException:
            await ctx.send(
                "Discord could not load that profile right now.",
                ephemeral=ctx.interaction is not None,
            )
            return
        if full_user.banner is None:
            await ctx.send(
                "That user does not have a visible profile banner.",
                ephemeral=ctx.interaction is not None,
            )
            return
        embed = discord.Embed(
            title=f"{full_user.name}'s banner",
            color=discord.Color.blurple(),
        )
        embed.set_image(url=full_user.banner.url)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="serverinfo",
        description="Show this server's size, ownership, and creation details.",
    )
    @commands.guild_only()
    async def serverinfo(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        guild = ctx.guild
        owner = guild.owner.mention if guild.owner is not None else f"`{guild.owner_id}`"
        embed = discord.Embed(
            title=f"Server information: {guild.name}",
            description=f"ID `{guild.id}` • Owner {owner}",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Created", value=_timestamp(guild.created_at))
        embed.add_field(name="Members", value=str(guild.member_count or "Unknown"))
        embed.add_field(name="Channels", value=str(len(guild.channels)))
        embed.add_field(name="Roles", value=str(max(0, len(guild.roles) - 1)))
        embed.add_field(name="Boost level", value=str(guild.premium_tier))
        embed.add_field(
            name="Verification",
            value=str(guild.verification_level).replace("_", " ").title(),
        )
        if guild.icon is not None:
            embed.set_thumbnail(url=guild.icon.url)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="roleinfo",
        description="Show a server role's color, position, and membership.",
    )
    @commands.guild_only()
    @app_commands.describe(role="The role to inspect.")
    async def roleinfo(self, ctx: commands.Context, role: discord.Role) -> None:
        embed = discord.Embed(
            title=f"Role information: {role.name}",
            description=f"{role.mention} • ID `{role.id}`",
            color=role.color if role.color.value else discord.Color.blurple(),
        )
        embed.add_field(name="Created", value=_timestamp(role.created_at))
        embed.add_field(name="Position", value=str(role.position))
        embed.add_field(name="Members", value=str(len(role.members)))
        embed.add_field(name="Managed", value="Yes" if role.managed else "No")
        embed.add_field(name="Mentionable", value="Yes" if role.mentionable else "No")
        permission_names = [
            name.replace("_", " ").title()
            for name, enabled in role.permissions
            if enabled
        ]
        embed.add_field(
            name="Granted permissions",
            value=", ".join(permission_names[:15]) or "No special permissions",
            inline=False,
        )
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="channelinfo",
        description="Show a server channel's type and settings.",
    )
    @commands.guild_only()
    @app_commands.describe(channel="A channel mention, ID, or exact name.")
    async def channelinfo(
        self,
        ctx: commands.Context,
        channel: str | None = None,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        target = (
            resolve_channel(ctx.guild, channel)
            if channel
            else ctx.channel
        )
        if target is None or not isinstance(target, discord.abc.GuildChannel):
            await ctx.send(
                "I could not find that channel in this server.",
                ephemeral=ctx.interaction is not None,
            )
            return
        embed = discord.Embed(
            title=f"Channel information: {target.name}",
            description=f"{target.mention} • ID `{target.id}`",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Type", value=type(target).__name__.replace("Channel", ""))
        embed.add_field(name="Created", value=_timestamp(target.created_at))
        if target.category is not None:
            embed.add_field(name="Category", value=target.category.name)
        if isinstance(target, discord.TextChannel):
            embed.add_field(name="Slowmode", value=f"{target.slowmode_delay} seconds")
            if target.topic:
                embed.add_field(name="Topic", value=target.topic[:1000], inline=False)
        elif isinstance(target, discord.VoiceChannel):
            embed.add_field(name="Bitrate", value=f"{target.bitrate // 1000} kbps")
            embed.add_field(name="User limit", value=str(target.user_limit or "Unlimited"))
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="botinfo",
        description="Show AEGIS runtime and account information.",
    )
    async def botinfo(self, ctx: commands.Context) -> None:
        user = self.bot.user
        if user is None:
            await ctx.send("AEGIS is still connecting.", ephemeral=ctx.interaction is not None)
            return
        cached_members = sum(guild.member_count or 0 for guild in self.bot.guilds)
        embed = discord.Embed(
            title="AEGIS information",
            description=f"{user.mention} • ID `{user.id}`",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Account created", value=_timestamp(user.created_at))
        embed.add_field(name="Servers", value=str(len(self.bot.guilds)))
        embed.add_field(name="Cached server members", value=str(cached_members))
        embed.add_field(name="Registered commands", value=str(sum(1 for _ in self.bot.walk_commands())))
        embed.add_field(name="Gateway latency", value=f"{round(self.bot.latency * 1000)} ms")
        embed.set_thumbnail(url=user.display_avatar.url)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="inviteinfo",
        description="Look up a Discord invite's server and usage details.",
    )
    @app_commands.describe(code="An invite URL or invite code.")
    async def inviteinfo(self, ctx: commands.Context, *, code: str) -> None:
        try:
            invite = await self.bot.fetch_invite(code.strip(), with_counts=True)
        except (discord.NotFound, discord.Forbidden):
            await ctx.send(
                "That invite could not be found or is not accessible.",
                ephemeral=ctx.interaction is not None,
            )
            return
        except discord.HTTPException:
            await ctx.send(
                "Discord could not look up that invite right now.",
                ephemeral=ctx.interaction is not None,
            )
            return
        guild = invite.guild
        embed = discord.Embed(
            title="Invite information",
            description=(
                f"Server: **{guild.name}** (`{guild.id}`)"
                if guild is not None
                else "This invite does not expose server details."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Members",
            value=str(getattr(guild, "approximate_member_count", None) or "Unknown"),
        )
        embed.add_field(
            name="Online",
            value=str(getattr(guild, "approximate_presence_count", None) or "Unknown"),
        )
        embed.add_field(name="Inviter", value=str(invite.inviter or "Unknown"))
        embed.add_field(name="Created", value=_timestamp(invite.created_at))
        embed.add_field(name="Expires", value=_timestamp(invite.expires_at))
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InformationCog(bot))
