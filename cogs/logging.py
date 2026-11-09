"""Logging setup, event toggles, ignore filters, and Discord event listeners."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.logging_manager import (
    DEFAULT_LOGGING_EVENTS,
    EVENT_LABELS,
    LoggingManager,
)
from database.repositories.community import CommunityRepository


logger = logging.getLogger(__name__)


def _manager(bot: commands.Bot) -> LoggingManager:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The community database is not initialized.")
    return LoggingManager(bot, repository)


def _member_roles(member: object) -> tuple[int, ...]:
    return tuple(int(role.id) for role in getattr(member, "roles", ()))


class LoggingCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = _manager(bot)

    @commands.hybrid_group(
        name="logging",
        description="Configure server event logs.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def logging(self, ctx: commands.Context) -> None:
        await ctx.send(
            "Use `logging setup`, `logging events`, `logging ignore`, "
            "`logging status`, or `logging disable`."
        )

    @logging.command(name="setup", description="Set the logging channel.")
    @commands.has_guild_permissions(manage_guild=True)
    async def setup_logging(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        config = await self.manager.repository.set_logging_config(
            guild_id=ctx.guild.id,
            channel_id=channel.id,
            enabled=True,
            enabled_events=DEFAULT_LOGGING_EVENTS,
        )
        await ctx.send(
            f"Logging is enabled in {channel.mention} for "
            f"{len(config.enabled_events)} event types.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @logging.command(
        name="events",
        description="Configure which logging events are enabled.",
    )
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.choices(
        event=[
            app_commands.Choice(name=label, value=event)
            for event, label in EVENT_LABELS.items()
        ]
    )
    async def configure_events(
        self,
        ctx: commands.Context,
        event: str,
        enabled: bool,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if event not in EVENT_LABELS:
            await ctx.send("That logging event is not supported.")
            return
        try:
            await self.manager.repository.set_logging_event(
                guild_id=ctx.guild.id,
                event=event,
                enabled=enabled,
            )
        except LookupError as exc:
            await ctx.send(str(exc))
            return
        state = "enabled" if enabled else "disabled"
        await ctx.send(f"{EVENT_LABELS[event]} {state}.")

    @logging.command(name="ignore", description="Add or remove a logging ignore.")
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.choices(
        kind=[
            app_commands.Choice(name="Channel", value="channel"),
            app_commands.Choice(name="User", value="user"),
            app_commands.Choice(name="Role", value="role"),
        ],
        action=[
            app_commands.Choice(name="Add", value="add"),
            app_commands.Choice(name="Remove", value="remove"),
        ],
    )
    @app_commands.describe(
        kind="Type of item to ignore.",
        target_id="ID of the channel, server member, or role.",
        action="Add or remove the ignore.",
    )
    async def configure_ignore(
        self,
        ctx: commands.Context,
        kind: str,
        target_id: int,
        action: str = "add",
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if kind not in {"channel", "user", "role"} or action not in {"add", "remove"}:
            await ctx.send("Use channel, user, or role and add or remove.")
            return
        if kind == "channel":
            target = ctx.guild.get_channel(target_id)
        elif kind == "role":
            target = ctx.guild.get_role(target_id)
        else:
            target = ctx.guild.get_member(target_id)
        if target is None:
            await ctx.send("That target was not found in this server.")
            return
        changed = await self.manager.repository.set_logging_ignore(
            guild_id=ctx.guild.id,
            target_type=kind,
            target_id=target_id,
            ignored=action == "add",
        )
        await ctx.send(
            f"{kind.title()} `{target_id}` "
            f"{'added to' if action == 'add' else 'removed from'} logging ignores."
            if changed
            else "No ignore setting changed."
        )

    @logging.command(name="status", description="Show current logging settings.")
    @commands.has_guild_permissions(manage_guild=True)
    async def logging_status(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        config = await self.manager.repository.get_logging_config(ctx.guild.id)
        if config is None:
            await ctx.send("Logging is not configured.")
            return
        enabled = set(config.enabled_events)
        active = [label for event, label in EVENT_LABELS.items() if event in enabled]
        disabled = [label for event, label in EVENT_LABELS.items() if event not in enabled]
        status = "Enabled" if config.enabled else "Disabled"
        details = [
            f"Logging: {status}",
            f"Channel: <#{config.channel_id}>",
            "Events on: " + (", ".join(active) or "None"),
            "Events off: " + (", ".join(disabled) or "None"),
            f"Ignored channel IDs: {', '.join(map(str, config.ignored_channels)) or 'None'}",
            f"Ignored user IDs: {', '.join(map(str, config.ignored_users)) or 'None'}",
            f"Ignored role IDs: {', '.join(map(str, config.ignored_roles)) or 'None'}",
        ]
        await ctx.send(
            "\n".join(details),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @logging.command(name="disable", description="Disable event logging.")
    @commands.has_guild_permissions(manage_guild=True)
    async def disable_logging(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self.manager.repository.set_logging_config(
                guild_id=ctx.guild.id,
                enabled=False,
            )
        except LookupError:
            await ctx.send("Logging is not configured.")
            return
        await ctx.send("Event logging disabled.")

    async def _log(
        self,
        guild: discord.Guild,
        event: str,
        text: str,
        *,
        channel_ids: tuple[int, ...] = (),
        user_ids: tuple[int, ...] = (),
        role_ids: tuple[int, ...] = (),
    ) -> None:
        try:
            await self.manager.send(
                guild=guild,
                event=event,
                content=text,
                channel_ids=channel_ids,
                user_ids=user_ids,
                role_ids=role_ids,
            )
        except discord.HTTPException:
            logger.warning("Could not send a %s log entry.", event)

    async def _executor(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        target_id: int,
    ) -> discord.User | discord.Member | None:
        return await self.manager.find_executor(
            guild,
            action=action,
            target_id=target_id,
        )

    @commands.Cog.listener()
    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        if before.guild is None or before.author.bot or before.content == after.content:
            return
        channel_id = before.channel.id
        text = (
            f"Message edited by {before.author.mention} in {before.channel.mention}.\n"
            f"Before: {before.content[:700] or '[empty]'}\n"
            f"After: {after.content[:700] or '[empty]'}"
        )
        await self._log(
            before.guild,
            "message_edit",
            text,
            channel_ids=(channel_id,),
            user_ids=(before.author.id,),
        )

    @commands.Cog.listener()
    async def on_raw_message_delete(
        self,
        payload: discord.RawMessageDeleteEvent,
    ) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None:
            return
        cached = payload.cached_message
        author_text = f" by <@{cached.author.id}>" if cached is not None else ""
        content_text = (
            f"\nContent: {cached.content[:700] or '[empty]'}"
            if cached is not None
            else "\nContent unavailable (message was not cached)."
        )
        await self._log(
            guild,
            "message_delete",
            f"Message `{payload.message_id}`{author_text} deleted in "
            f"<#{payload.channel_id}>.{content_text}",
            channel_ids=(payload.channel_id,),
            user_ids=(cached.author.id,) if cached is not None else (),
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._log(
            member.guild,
            "member_join",
            f"{member.mention} joined the server.",
            user_ids=(member.id,),
            role_ids=_member_roles(member),
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        executor = await self._executor(
            member.guild,
            discord.AuditLogAction.kick,
            member.id,
        )
        if executor is None:
            await self._log(
                member.guild,
                "member_leave",
                f"{member} left the server.",
                user_ids=(member.id,),
                role_ids=_member_roles(member),
            )
            return
        await self._log(
            member.guild,
            "kick",
            f"{member} was kicked. Executor: {executor.mention}.",
            user_ids=(member.id, executor.id),
            role_ids=_member_roles(member),
        )

    @commands.Cog.listener()
    async def on_member_ban(
        self,
        guild: discord.Guild,
        user: discord.User,
    ) -> None:
        executor = await self._executor(
            guild,
            discord.AuditLogAction.ban,
            user.id,
        )
        suffix = f" Executor: {executor.mention}." if executor else ""
        await self._log(
            guild,
            "ban",
            f"{user} was banned.{suffix}",
            user_ids=(user.id, executor.id) if executor else (user.id,),
        )

    @commands.Cog.listener()
    async def on_member_unban(
        self,
        guild: discord.Guild,
        user: discord.User,
    ) -> None:
        executor = await self._executor(
            guild,
            discord.AuditLogAction.unban,
            user.id,
        )
        suffix = f" Executor: {executor.mention}." if executor else ""
        await self._log(
            guild,
            "unban",
            f"{user} was unbanned.{suffix}",
            user_ids=(user.id, executor.id) if executor else (user.id,),
        )

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ) -> None:
        guild = after.guild
        before_role_ids = {role.id for role in before.roles}
        after_role_ids = {role.id for role in after.roles}
        if before_role_ids != after_role_ids:
            added = [role.name for role in after.roles if role.id not in before_role_ids]
            removed = [role.name for role in before.roles if role.id not in after_role_ids]
            details = []
            if added:
                details.append("Added: " + ", ".join(added))
            if removed:
                details.append("Removed: " + ", ".join(removed))
            executor = await self._executor(
                guild,
                discord.AuditLogAction.member_role_update,
                after.id,
            )
            suffix = f"\nExecutor: {executor.mention}" if executor else ""
            await self._log(
                guild,
                "member_role_update",
                f"Roles changed for {after.mention}: {'; '.join(details)}.{suffix}",
                user_ids=(after.id, executor.id) if executor else (after.id,),
                role_ids=tuple(before_role_ids | after_role_ids),
            )
        if before.nick != after.nick:
            executor = await self._executor(
                guild,
                discord.AuditLogAction.member_update,
                after.id,
            )
            suffix = f"\nExecutor: {executor.mention}" if executor else ""
            await self._log(
                guild,
                "nickname_update",
                f"Nickname changed for {after.mention}: "
                f"{before.nick or before.name} → {after.nick or after.name}.{suffix}",
                user_ids=(after.id, executor.id) if executor else (after.id,),
                role_ids=tuple(before_role_ids | after_role_ids),
            )
        if before.timed_out_until != after.timed_out_until:
            executor = await self._executor(
                guild,
                discord.AuditLogAction.member_update,
                after.id,
            )
            suffix = f" Executor: {executor.mention}." if executor else ""
            state = (
                f"until {after.timed_out_until.isoformat()}"
                if after.timed_out_until
                else "cleared"
            )
            await self._log(
                guild,
                "timeout",
                f"Timeout for {after.mention} {state}.{suffix}",
                user_ids=(after.id, executor.id) if executor else (after.id,),
                role_ids=tuple(before_role_ids | after_role_ids),
            )

    @commands.Cog.listener()
    async def on_guild_channel_create(
        self,
        channel: discord.abc.GuildChannel,
    ) -> None:
        executor = await self._executor(
            channel.guild,
            discord.AuditLogAction.channel_create,
            channel.id,
        )
        suffix = f" Executor: {executor.mention}." if executor else ""
        await self._log(
            channel.guild,
            "channel_create",
            f"Channel {channel.mention} created.{suffix}",
            channel_ids=(channel.id,),
            user_ids=(executor.id,) if executor else (),
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self,
        channel: discord.abc.GuildChannel,
    ) -> None:
        executor = await self._executor(
            channel.guild,
            discord.AuditLogAction.channel_delete,
            channel.id,
        )
        suffix = f" Executor: {executor.mention}." if executor else ""
        await self._log(
            channel.guild,
            "channel_delete",
            f"Channel `#{channel.name}` deleted.{suffix}",
            channel_ids=(channel.id,),
            user_ids=(executor.id,) if executor else (),
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"Name: {before.name} → {after.name}")
        if getattr(before, "topic", None) != getattr(after, "topic", None):
            changes.append("Topic changed")
        if getattr(before, "category_id", None) != getattr(after, "category_id", None):
            changes.append("Category changed")
        if not changes:
            return
        executor = await self._executor(
            after.guild,
            discord.AuditLogAction.channel_update,
            after.id,
        )
        suffix = f"\nExecutor: {executor.mention}" if executor else ""
        await self._log(
            after.guild,
            "channel_update",
            f"Channel <#{after.id}> updated: {'; '.join(changes)}.{suffix}",
            channel_ids=(before.id, after.id),
            user_ids=(executor.id,) if executor else (),
        )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        executor = await self._executor(
            role.guild,
            discord.AuditLogAction.role_create,
            role.id,
        )
        suffix = f" Executor: {executor.mention}." if executor else ""
        await self._log(
            role.guild,
            "role_create",
            f"Role {role.mention} created.{suffix}",
            user_ids=(executor.id,) if executor else (),
            role_ids=(role.id,),
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        executor = await self._executor(
            role.guild,
            discord.AuditLogAction.role_delete,
            role.id,
        )
        suffix = f" Executor: {executor.mention}." if executor else ""
        await self._log(
            role.guild,
            "role_delete",
            f"Role `{role.name}` deleted.{suffix}",
            user_ids=(executor.id,) if executor else (),
            role_ids=(role.id,),
        )

    @commands.Cog.listener()
    async def on_guild_role_update(
        self,
        before: discord.Role,
        after: discord.Role,
    ) -> None:
        changes = []
        if before.name != after.name:
            changes.append(f"Name: {before.name} → {after.name}")
        if before.permissions.value != after.permissions.value:
            changes.append("Permissions changed")
        if before.color != after.color:
            changes.append("Color changed")
        if before.hoist != after.hoist or before.mentionable != after.mentionable:
            changes.append("Display settings changed")
        if not changes:
            return
        executor = await self._executor(
            after.guild,
            discord.AuditLogAction.role_update,
            after.id,
        )
        suffix = f"\nExecutor: {executor.mention}" if executor else ""
        await self._log(
            after.guild,
            "role_update",
            f"Role `{after.name}` updated: {'; '.join(changes)}.{suffix}",
            user_ids=(executor.id,) if executor else (),
            role_ids=(before.id, after.id),
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel == after.channel:
            return
        if before.channel is None and after.channel is not None:
            event, action = "voice_join", f"joined {after.channel.mention}"
        elif after.channel is None and before.channel is not None:
            event, action = "voice_leave", f"left {before.channel.mention}"
        else:
            event = "voice_move"
            action = f"moved from {before.channel.mention} to {after.channel.mention}"
        channel_ids = tuple(
            channel.id for channel in (before.channel, after.channel) if channel is not None
        )
        await self._log(
            member.guild,
            event,
            f"{member.mention} {action}.",
            channel_ids=channel_ids,
            user_ids=(member.id,),
            role_ids=_member_roles(member),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingCog(bot))
