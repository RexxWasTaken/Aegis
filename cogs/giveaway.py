"""Prefix and slash commands for reaction-entry giveaways."""

from __future__ import annotations

import discord
from discord.ext import commands, tasks

from core.giveaway_manager import GiveawayManager, GiveawayManagerError
from database.repositories.community import CommunityRepository
from embeds.giveaway import giveaway_list_embed
from utils.duration import parse_duration


def _manager(bot: commands.Bot) -> GiveawayManager:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The community database is not initialized.")
    return GiveawayManager(bot, repository)


class GiveawayCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = _manager(bot)
        self.expire_due_giveaways.start()

    def cog_unload(self) -> None:
        self.expire_due_giveaways.cancel()

    @tasks.loop(seconds=30)
    async def expire_due_giveaways(self) -> None:
        await self.manager.finish_due_giveaways()

    @expire_due_giveaways.before_loop
    async def before_expiry_loop(self) -> None:
        await self.bot.wait_until_ready()

    @commands.hybrid_group(
        name="giveaway",
        description="Manage AEGIS custom-reaction giveaways.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def giveaway(self, ctx: commands.Context) -> None:
        """Show active giveaways when no subcommand is supplied."""
        guild = ctx.guild
        if guild is None:
            raise commands.NoPrivateMessage()
        records = await self.manager.repository.list_giveaways(guild_id=guild.id)
        await ctx.send(embed=giveaway_list_embed(records))

    async def _require_guild_giveaway(
        self, ctx: commands.Context, message_id: int
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        giveaway = await self.manager.repository.get_giveaway(message_id)
        if giveaway is None:
            raise GiveawayManagerError("No giveaway is registered for that message ID.")
        if giveaway.guild_id != ctx.guild.id:
            raise GiveawayManagerError("That giveaway belongs to another server.")

    @giveaway.command(
        name="start",
        description="Start a giveaway using the AEGIS custom reaction.",
    )
    @commands.has_guild_permissions(manage_guild=True)
    async def start(
        self,
        ctx: commands.Context,
        duration: str,
        winner_count: int,
        *,
        prize: str,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if not isinstance(ctx.channel, discord.TextChannel):
            raise commands.BadArgument("Start giveaways in a server text channel.")
        try:
            parsed_duration = parse_duration(duration)
            record = await self.manager.start(
                channel=ctx.channel,
                host=ctx.author,
                prize=prize,
                duration=parsed_duration,
                winner_count=winner_count,
            )
        except (ValueError, GiveawayManagerError) as exc:
            await ctx.send(str(exc))
            return
        await ctx.send(
            f"Giveaway started. Announcement message ID: `{record.message_id}`."
        )

    @giveaway.command(name="end", description="End an active giveaway.")
    @commands.has_guild_permissions(manage_guild=True)
    async def end(self, ctx: commands.Context, message_id: int) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self._require_guild_giveaway(ctx, message_id)
            await self.manager.end(message_id)
        except (GiveawayManagerError, ValueError) as exc:
            await ctx.send(str(exc))
            return
        await ctx.send(f"Giveaway `{message_id}` ended.")

    @giveaway.command(name="reroll", description="Reroll an ended giveaway.")
    @commands.has_guild_permissions(manage_guild=True)
    async def reroll(self, ctx: commands.Context, message_id: int) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self._require_guild_giveaway(ctx, message_id)
            _, winners = await self.manager.end(message_id, reroll=True)
        except (GiveawayManagerError, ValueError) as exc:
            await ctx.send(str(exc))
            return
        if not winners:
            await ctx.send(f"No new eligible participants were found for `{message_id}`.")
            return
        await ctx.send(f"Giveaway `{message_id}` was rerolled.")

    @giveaway.command(name="pause", description="Pause an active giveaway.")
    @commands.has_guild_permissions(manage_guild=True)
    async def pause(self, ctx: commands.Context, message_id: int) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self._require_guild_giveaway(ctx, message_id)
            await self.manager.pause(message_id)
        except (GiveawayManagerError, ValueError) as exc:
            await ctx.send(str(exc))
            return
        await ctx.send(f"Giveaway `{message_id}` was paused.")

    @giveaway.command(name="resume", description="Resume a paused giveaway.")
    @commands.has_guild_permissions(manage_guild=True)
    async def resume(self, ctx: commands.Context, message_id: int) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self._require_guild_giveaway(ctx, message_id)
            await self.manager.resume(message_id)
        except (GiveawayManagerError, ValueError) as exc:
            await ctx.send(str(exc))
            return
        await ctx.send(f"Giveaway `{message_id}` was resumed.")

    @giveaway.command(name="list", description="List active and paused giveaways.")
    @commands.has_guild_permissions(manage_guild=True)
    async def list_giveaways(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        records = await self.manager.repository.list_giveaways(guild_id=ctx.guild.id)
        await ctx.send(embed=giveaway_list_embed(records))

    @giveaway.command(name="delete", description="Delete a giveaway and its announcement.")
    @commands.has_guild_permissions(manage_guild=True)
    async def delete(self, ctx: commands.Context, message_id: int) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self._require_guild_giveaway(ctx, message_id)
            await self.manager.delete(message_id)
        except (GiveawayManagerError, ValueError) as exc:
            await ctx.send(str(exc))
            return
        await ctx.send(f"Giveaway `{message_id}` and its announcement were deleted.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GiveawayCog(bot))
