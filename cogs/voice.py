"""Voice channel and voice-state information without opening another player."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


def voice_state_summary(state: discord.VoiceState) -> str:
    """Return the useful connection flags for a member's current voice state."""
    flags = (
        ("Self-muted", state.self_mute),
        ("Self-deafened", state.self_deaf),
        ("Server-muted", state.mute),
        ("Server-deafened", state.deaf),
        ("Streaming", state.self_stream),
        ("Camera on", state.self_video),
        ("Suppressed on stage", state.suppress),
    )
    enabled = [label for label, active in flags if active]
    return ", ".join(enabled) if enabled else "No mute, deaf, stream, or camera flags"


class VoiceCog(commands.Cog):
    """Voice inspection commands that leave the music connection untouched."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="voiceinfo",
        description="Show a voice channel's occupancy and settings.",
    )
    @commands.guild_only()
    @app_commands.describe(channel="The voice channel; defaults to your current channel.")
    async def voiceinfo(
        self,
        ctx: commands.Context,
        channel: discord.VoiceChannel | None = None,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        target = channel
        if target is None and isinstance(ctx.author, discord.Member):
            target = (
                ctx.author.voice.channel
                if ctx.author.voice is not None
                and isinstance(ctx.author.voice.channel, discord.VoiceChannel)
                else None
            )
        if target is None:
            await ctx.send(
                "Choose a voice channel or join one first.",
                ephemeral=ctx.interaction is not None,
            )
            return
        members = target.members
        embed = discord.Embed(
            title=f"Voice channel: {target.name}",
            description=f"{target.mention} • ID `{target.id}`",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Members connected", value=str(len(members)))
        embed.add_field(name="User limit", value=str(target.user_limit or "Unlimited"))
        embed.add_field(name="Bitrate", value=f"{target.bitrate // 1000} kbps")
        embed.add_field(
            name="Connected members",
            value=", ".join(member.display_name for member in members[:20]) or "No one",
            inline=False,
        )
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="voicestate",
        description="Show a member's current voice connection state.",
    )
    @commands.guild_only()
    @app_commands.describe(member="The member to inspect; defaults to you.")
    async def voicestate(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        target = member or ctx.author
        if not isinstance(target, discord.Member):
            await ctx.send(
                "That user is not a member of this server.",
                ephemeral=ctx.interaction is not None,
            )
            return
        state = target.voice
        if state is None or state.channel is None:
            await ctx.send(
                f"{target.display_name} is not connected to voice.",
                ephemeral=ctx.interaction is not None,
            )
            return
        embed = discord.Embed(
            title=f"Voice state: {target.display_name}",
            description=(
                f"{target.mention} in {state.channel.mention}\n"
                f"{voice_state_summary(state)}"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="voiceusers",
        description="List members currently connected to a voice channel.",
    )
    @commands.guild_only()
    @app_commands.describe(channel="The voice channel; defaults to your current channel.")
    async def voiceusers(
        self,
        ctx: commands.Context,
        channel: discord.VoiceChannel | None = None,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        target = channel
        if target is None and isinstance(ctx.author, discord.Member):
            target = (
                ctx.author.voice.channel
                if ctx.author.voice is not None
                and isinstance(ctx.author.voice.channel, discord.VoiceChannel)
                else None
            )
        if target is None:
            await ctx.send(
                "Choose a voice channel or join one first.",
                ephemeral=ctx.interaction is not None,
            )
            return
        names = [member.display_name for member in target.members if not member.bot]
        description = "\n".join(f"• {name}" for name in names[:50]) or "No human members are connected."
        embed = discord.Embed(
            title=f"Voice members: {target.name}",
            description=description,
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceCog(bot))
