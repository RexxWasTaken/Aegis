"""Channel lock, restore, and slowmode moderation commands."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from cogs.moderation.utilities import BulkActionConfirmationView
from core.checks import has_guild_permission
from embeds.moderation import confirmation_embed, success_embed
from embeds.moderation_errors import operation_error_embed
from services.moderation_service import ModerationServiceError


logger = logging.getLogger(__name__)
MAX_SLOWMODE_SECONDS = 6 * 60 * 60


class ChannelModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _repository(self):
        repository = getattr(self.bot, "moderation_repository", None)
        if repository is None:
            service = getattr(self.bot, "moderation_service", None)
            repository = getattr(service, "repository", None)
        if repository is None:
            raise RuntimeError("The moderation repository is not initialized.")
        return repository

    async def _bot_member(self, guild: discord.Guild) -> discord.Member:
        if guild.me is not None:
            return guild.me
        if self.bot.user is None:
            raise RuntimeError("The bot user is not available yet.")
        return await guild.fetch_member(self.bot.user.id)

    def _channel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None,
    ):
        selected = channel or ctx.channel
        if (
            selected is None
            or getattr(getattr(selected, "guild", None), "id", None) != ctx.guild.id
            or not hasattr(selected, "set_permissions")
        ):
            raise commands.BadArgument("Choose a text channel in this server.")
        return selected

    async def _require_bot_permission(
        self,
        channel: discord.abc.GuildChannel,
        bot_member: discord.Member,
        permission: str,
    ) -> None:
        permissions = channel.permissions_for(bot_member)
        if not bool(getattr(permissions, permission, False)):
            raise commands.BotMissingPermissions([permission])

    async def _lock_one(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        bot_member: discord.Member,
        reason: str,
    ) -> None:
        await self._require_bot_permission(channel, bot_member, "manage_roles")
        default_role = guild.default_role
        overwrite = channel.overwrites_for(default_role)
        previous = overwrite.send_messages
        inserted = await self._repository().save_channel_lock_state(
            guild_id=guild.id,
            channel_id=channel.id,
            target_id=default_role.id,
            previous_send_messages=previous,
        )
        overwrite.send_messages = False
        try:
            await channel.set_permissions(
                default_role, overwrite=overwrite, reason=reason[:512]
            )
        except discord.HTTPException:
            if inserted:
                await self._repository().delete_channel_lock_state(
                    guild_id=guild.id,
                    channel_id=channel.id,
                    target_id=default_role.id,
                )
            raise

    async def _unlock_one(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        bot_member: discord.Member,
        reason: str,
    ) -> bool:
        await self._require_bot_permission(channel, bot_member, "manage_roles")
        default_role = guild.default_role
        repository = self._repository()
        state = await repository.get_channel_lock_state(
            guild_id=guild.id,
            channel_id=channel.id,
            target_id=default_role.id,
        )
        if state is None:
            return False
        overwrite = channel.overwrites_for(default_role)
        overwrite.send_messages = state.previous_send_messages
        await channel.set_permissions(
            default_role, overwrite=overwrite, reason=reason[:512]
        )
        await repository.delete_channel_lock_state(
            guild_id=guild.id,
            channel_id=channel.id,
            target_id=default_role.id,
        )
        return True

    @commands.command(name="lock")
    @commands.guild_only()
    @has_guild_permission("manage_channels")
    async def lock(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Deny @everyone send access while preserving other channel overrides."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        selected = self._channel(ctx, channel)
        bot_member = await self._bot_member(ctx.guild)
        await self._lock_one(
            guild=ctx.guild,
            channel=selected,
            bot_member=bot_member,
            reason=reason,
        )
        await ctx.send(
            embed=success_embed("lock", channel=selected, reason=reason, guild=ctx.guild),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="unlock")
    @commands.guild_only()
    @has_guild_permission("manage_channels")
    async def unlock(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Restore the channel's saved @everyone send permission."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        selected = self._channel(ctx, channel)
        bot_member = await self._bot_member(ctx.guild)
        restored = await self._unlock_one(
            guild=ctx.guild,
            channel=selected,
            bot_member=bot_member,
            reason=reason,
        )
        if not restored:
            raise ModerationServiceError(
                f"No saved lock state exists for {selected.mention}; no permissions changed."
            )
        await ctx.send(
            embed=success_embed(
                "unlock", channel=selected, reason=reason, guild=ctx.guild
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _bulk_channel_action(
        self, ctx: commands.Context, *, lock_channels: bool
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        guild = ctx.guild
        bot_member = await self._bot_member(guild)
        repository = self._repository()
        channels = list(guild.text_channels)
        if not lock_channels:
            eligible = []
            for channel in channels:
                state = await repository.get_channel_lock_state(
                    guild_id=guild.id,
                    channel_id=channel.id,
                    target_id=guild.default_role.id,
                )
                if state is not None:
                    eligible.append(channel)
            channels = eligible
        if not channels:
            message = (
                "There are no eligible text channels to lock."
                if lock_channels
                else "There are no saved channel locks to restore."
            )
            await ctx.send(
                embed=operation_error_embed(message, guild=guild),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        command_name = "lockall" if lock_channels else "unlockall"
        view = BulkActionConfirmationView(ctx.author.id)
        confirmation = await ctx.send(
            embed=confirmation_embed(
                command_name, count=len(channels), guild=guild
            ),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await view.wait()
        if view.value is not True:
            await confirmation.edit(view=None)
            label = "Lockall" if lock_channels else "Unlockall"
            status = "cancelled" if view.value is False else "confirmation expired"
            await ctx.send(
                embed=operation_error_embed(
                    f"{label} {status}; no channels were changed.", guild=guild
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await confirmation.edit(view=None)

        completed = 0
        skipped = 0
        for channel in channels:
            try:
                if lock_channels:
                    await self._lock_one(
                        guild=guild,
                        channel=channel,
                        bot_member=bot_member,
                        reason=f"lockall requested by moderator {ctx.author.id}",
                    )
                    completed += 1
                elif await self._unlock_one(
                    guild=guild,
                    channel=channel,
                    bot_member=bot_member,
                    reason=f"unlockall requested by moderator {ctx.author.id}",
                ):
                    completed += 1
                else:
                    skipped += 1
            except (discord.Forbidden, discord.HTTPException, commands.BotMissingPermissions):
                skipped += 1
                logger.info(
                    "Skipped %s during %s due to an inaccessible permission update.",
                    channel.id,
                    command_name,
                    exc_info=True,
                )
        if completed == 0:
            await ctx.send(
                embed=operation_error_embed(
                    f"No channels were changed; {skipped} channel(s) were skipped.",
                    guild=guild,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await ctx.send(
            embed=success_embed(
                command_name,
                count=completed,
                skipped_count=skipped,
                guild=guild,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="lockall")
    @commands.guild_only()
    @has_guild_permission("manage_channels")
    async def lockall(self, ctx: commands.Context) -> None:
        """Confirm, then lock eligible text channels in this server."""
        await self._bulk_channel_action(ctx, lock_channels=True)

    @commands.command(name="unlockall")
    @commands.guild_only()
    @has_guild_permission("manage_channels")
    async def unlockall(self, ctx: commands.Context) -> None:
        """Confirm, then restore only send permissions saved by AEGIS."""
        await self._bulk_channel_action(ctx, lock_channels=False)

    @commands.command(name="slowmode")
    @commands.guild_only()
    @has_guild_permission("manage_channels")
    async def slowmode(
        self,
        ctx: commands.Context,
        seconds: int,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Set or disable slowmode from 0 to 21600 seconds."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if not 0 <= seconds <= MAX_SLOWMODE_SECONDS:
            raise commands.BadArgument(
                f"Slowmode must be between 0 and {MAX_SLOWMODE_SECONDS} seconds."
            )
        selected = self._channel(ctx, channel)
        bot_member = await self._bot_member(ctx.guild)
        await self._require_bot_permission(selected, bot_member, "manage_channels")
        await selected.edit(
            slowmode_delay=seconds,
            reason=f"slowmode requested by moderator {ctx.author.id}",
        )
        await ctx.send(
            embed=success_embed(
                "slowmode",
                channel=selected,
                seconds=seconds,
                guild=ctx.guild,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChannelModerationCog(bot))
