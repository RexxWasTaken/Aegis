"""Guild configuration and event listeners for opt-in anti-abuse protection."""

from __future__ import annotations

from dataclasses import replace
import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.security import SecurityManager
from database.repositories.community import CommunityRepository


logger = logging.getLogger(__name__)


def _repository(bot: commands.Bot) -> CommunityRepository:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The community database is not initialized.")
    return repository


class SecurityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.repository = _repository(bot)
        self.manager = SecurityManager(bot, self.repository)

    async def _save_config(self, ctx: commands.Context, **changes: object) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        current = await self.repository.get_security_config(ctx.guild.id)
        try:
            updated = await self.repository.set_security_config(
                replace(current, **changes)
            )
        except (TypeError, ValueError) as exc:
            await ctx.send(str(exc), ephemeral=ctx.interaction is not None)
            return
        await ctx.send(
            f"Security settings saved. Detection is **{'on' if updated.enabled else 'off'}**; "
            f"action mode: `{updated.action}`.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_group(
        name="security",
        description="View or configure this server's security protections.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def security(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        config = await self.repository.get_security_config(ctx.guild.id)
        channel = (
            f"<#{config.log_channel_id}>"
            if config.log_channel_id is not None
            else "not configured"
        )
        await ctx.send(
            f"Security protection: **{'enabled' if config.enabled else 'disabled'}**\n"
            f"Action mode: `{config.action}` (default is log-only)\n"
            f"Threshold: **{config.threshold}** actions in **{config.window_seconds}s**\n"
            f"Mass-mention limit: **{config.mention_limit}** users/roles\n"
            f"Alert channel: {channel}\n"
            "Configure with `security enable`, `security log`, `security threshold`, "
            "and `security action`.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @security.command(name="enable", description="Enable security event monitoring.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def security_enable(self, ctx: commands.Context) -> None:
        await self._save_config(ctx, enabled=True)
        if ctx.guild is not None:
            config = await self.repository.get_security_config(ctx.guild.id)
            if config.log_channel_id is None:
                logger.warning(
                    "Security protection enabled without a configured alert channel in guild %s.",
                    ctx.guild.id,
                )

    @security.command(name="disable", description="Disable security event monitoring.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def security_disable(self, ctx: commands.Context) -> None:
        await self._save_config(ctx, enabled=False)

    @security.command(
        name="threshold",
        description="Set the audit-action count and detection window.",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(
        count="Actions needed to trigger an alert (2–10).",
        window_seconds="Detection window in seconds (5–60).",
    )
    async def security_threshold(
        self,
        ctx: commands.Context,
        count: int,
        window_seconds: int = 15,
    ) -> None:
        await self._save_config(
            ctx,
            threshold=count,
            window_seconds=window_seconds,
        )

    @security.command(
        name="mentionlimit",
        description="Set how many mentions trigger a security alert.",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(count="User and role mentions allowed in one message (2–50).")
    async def security_mentionlimit(
        self,
        ctx: commands.Context,
        count: int,
    ) -> None:
        await self._save_config(ctx, mention_limit=count)

    @security.command(
        name="log",
        description="Set or clear the security alert channel.",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(channel="Text channel for alerts, or leave empty to clear it.")
    async def security_log(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel | None = None,
    ) -> None:
        channel_id = channel.id if channel is not None else None
        await self._save_config(ctx, log_channel_id=channel_id)

    @security.command(
        name="action",
        description="Choose log-only alerts or explicitly enable a kick response.",
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(mode="`log` is safe by default; `kick` requires a valid hierarchy.")
    async def security_action(
        self,
        ctx: commands.Context,
        mode: str,
    ) -> None:
        if mode.casefold() not in ("log", "kick"):
            await ctx.send(
                "Choose `log` or `kick`. Log-only is the default.",
                ephemeral=ctx.interaction is not None,
            )
            return
        await self._save_config(ctx, action=mode.casefold())

    @security.group(
        name="trusted",
        description="Manage members protected from automatic security action.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def security_trusted(self, ctx: commands.Context) -> None:
        await self._send_trusted_users(ctx)

    async def _send_trusted_users(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        user_ids = await self.repository.list_security_trusted_users(
            guild_id=ctx.guild.id
        )
        if not user_ids:
            body = "The trusted list is empty."
        else:
            body = (
                f"Trusted members ({len(user_ids)}): "
                + ", ".join(f"`{user_id}`" for user_id in user_ids[:30])
            )
            if len(user_ids) > 30:
                body += f"\n…and {len(user_ids) - 30} more."
        await ctx.send(
            body,
            ephemeral=ctx.interaction is not None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @security_trusted.command(name="list", description="List protected members.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def security_trusted_list(self, ctx: commands.Context) -> None:
        await self._send_trusted_users(ctx)

    @security_trusted.command(name="add", description="Protect a member from automatic action.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(member="The server member to trust.")
    async def security_trusted_add(
        self,
        ctx: commands.Context,
        member: discord.Member,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        created = await self.repository.add_security_trusted_user(
            guild_id=ctx.guild.id,
            user_id=member.id,
            added_by=ctx.author.id,
        )
        await ctx.send(
            f"{member.mention} {'added to' if created else 'is already on'} the trusted list.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @security_trusted.command(name="remove", description="Remove a member from the trusted list.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(member="The server member to remove from the trusted list.")
    async def security_trusted_remove(
        self,
        ctx: commands.Context,
        member: discord.Member,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        removed = await self.repository.remove_security_trusted_user(
            guild_id=ctx.guild.id,
            user_id=member.id,
        )
        await ctx.send(
            f"{member.mention} {'removed from' if removed else 'was not on'} the trusted list.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_guild_channel_create(
        self,
        channel: discord.abc.GuildChannel,
    ) -> None:
        await self.manager.handle_audit_event(
            channel.guild,
            event="channel_create",
            target_id=channel.id,
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self,
        channel: discord.abc.GuildChannel,
    ) -> None:
        await self.manager.handle_audit_event(
            channel.guild,
            event="channel_delete",
            target_id=channel.id,
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(
        self,
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> None:
        if before.overwrites == after.overwrites:
            return
        await self.manager.handle_audit_event(
            after.guild,
            event="channel_update",
            target_id=after.id,
        )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        await self.manager.handle_audit_event(
            role.guild,
            event="role_create",
            target_id=role.id,
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        await self.manager.handle_audit_event(
            role.guild,
            event="role_delete",
            target_id=role.id,
        )

    @commands.Cog.listener()
    async def on_guild_role_update(
        self,
        before: discord.Role,
        after: discord.Role,
    ) -> None:
        if before.permissions.value == after.permissions.value:
            return
        await self.manager.handle_audit_event(
            after.guild,
            event="role_update",
            target_id=after.id,
        )

    @commands.Cog.listener()
    async def on_member_ban(
        self,
        guild: discord.Guild,
        user: discord.User,
    ) -> None:
        await self.manager.handle_audit_event(
            guild,
            event="member_ban",
            target_id=user.id,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self.manager.handle_audit_event(
            member.guild,
            event="member_kick",
            target_id=member.id,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            await self.manager.handle_audit_event(
                member.guild,
                event="bot_add",
                target_id=member.id,
            )

    @commands.Cog.listener()
    async def on_webhooks_update(
        self,
        channel: discord.abc.GuildChannel,
    ) -> None:
        await self.manager.handle_audit_event(
            channel.guild,
            event="webhook_update",
            target_id=None,
            channel_id=channel.id,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        try:
            await self.manager.handle_mass_mention(message)
        except Exception:
            logger.exception("Could not process a security message event.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SecurityCog(bot))
