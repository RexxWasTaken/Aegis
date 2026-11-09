"""Opt-in, guild-scoped anti-abuse detection with conservative defaults."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

import discord

from database.repositories.community import CommunityRepository, SecurityConfig


logger = logging.getLogger(__name__)

_AUDIT_ACTIONS = {
    "channel_create": discord.AuditLogAction.channel_create,
    "channel_delete": discord.AuditLogAction.channel_delete,
    "channel_update": discord.AuditLogAction.channel_update,
    "role_create": discord.AuditLogAction.role_create,
    "role_delete": discord.AuditLogAction.role_delete,
    "role_update": discord.AuditLogAction.role_update,
    "member_ban": discord.AuditLogAction.ban,
    "member_kick": discord.AuditLogAction.kick,
    "webhook_create": discord.AuditLogAction.webhook_create,
    "webhook_delete": discord.AuditLogAction.webhook_delete,
    "bot_add": discord.AuditLogAction.bot_add,
}
_EVENT_LABELS = {
    "channel_create": "channel creations",
    "channel_delete": "channel deletions",
    "channel_update": "channel permission changes",
    "role_create": "role creations",
    "role_delete": "role deletions",
    "role_update": "role permission changes",
    "member_ban": "member bans",
    "member_kick": "member kicks",
    "webhook_create": "webhook creations",
    "webhook_delete": "webhook deletions",
    "bot_add": "bot additions",
    "mass_mention": "mass-mention messages",
}


class SecurityManager:
    """Correlate audit-log actions and only punish after explicit opt-in."""

    def __init__(
        self,
        bot: discord.Client,
        repository: CommunityRepository,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self._recent_events: dict[tuple[int, int], deque[float]] = defaultdict(deque)
        self._last_alert: dict[tuple[int, int], float] = {}

    def record_event(
        self,
        *,
        guild_id: int,
        actor_id: int,
        window_seconds: int,
        now: float | None = None,
    ) -> int:
        """Count recent actions by actor across protected event categories."""
        current = time.monotonic() if now is None else now
        events = self._recent_events[(guild_id, actor_id)]
        cutoff = current - window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        events.append(current)
        return len(events)

    def _should_alert(self, guild_id: int, actor_id: int, now: float) -> bool:
        key = (guild_id, actor_id)
        previous = self._last_alert.get(key)
        if previous is not None and now - previous < 60:
            return False
        self._last_alert[key] = now
        return True

    async def _find_audit_entry(
        self,
        guild: discord.Guild,
        *,
        event: str,
        target_id: int | None,
        channel_id: int | None = None,
        max_age_seconds: int = 15,
    ) -> Any | None:
        action = _AUDIT_ACTIONS.get(event)
        if action is None:
            return None
        bot_member = guild.me
        permissions = getattr(bot_member, "guild_permissions", None)
        if not bool(getattr(permissions, "view_audit_log", False)):
            return None

        for attempt in range(2):
            now = datetime.now(timezone.utc)
            try:
                async for entry in guild.audit_logs(limit=10, action=action):
                    created_at = getattr(entry, "created_at", None)
                    if created_at is None or created_at.tzinfo is None:
                        continue
                    age = (now - created_at).total_seconds()
                    if age < 0 or age > max_age_seconds:
                        continue
                    target = getattr(entry, "target", None)
                    if target_id is not None and getattr(target, "id", None) == target_id:
                        return entry
                    if channel_id is not None:
                        extra = getattr(entry, "extra", None)
                        extra_channel = getattr(extra, "channel", None)
                        if getattr(extra_channel, "id", None) == channel_id:
                            return entry
            except (discord.Forbidden, discord.HTTPException):
                logger.debug("Audit-log lookup unavailable for guild %s.", guild.id)
                return None
            if attempt == 0:
                await asyncio.sleep(0.25)
        return None

    async def find_executor(
        self,
        guild: discord.Guild,
        *,
        event: str,
        target_id: int | None,
        channel_id: int | None = None,
    ) -> discord.User | discord.Member | None:
        """Find the recent audit-log executor, never guessing on a mismatch."""
        entry = await self._find_audit_entry(
            guild,
            event=event,
            target_id=target_id,
            channel_id=channel_id,
        )
        return getattr(entry, "user", None) if entry is not None else None

    async def handle_audit_event(
        self,
        guild: discord.Guild,
        *,
        event: str,
        target_id: int | None,
        channel_id: int | None = None,
    ) -> bool:
        config = await self.repository.get_security_config(guild.id)
        if not config.enabled:
            return False
        if event == "webhook_update":
            matches = []
            for webhook_event in ("webhook_create", "webhook_delete"):
                entry = await self._find_audit_entry(
                    guild,
                    event=webhook_event,
                    target_id=None,
                    channel_id=channel_id,
                )
                if entry is not None:
                    matches.append((entry.created_at, webhook_event, entry.user))
            if not matches:
                return False
            _, resolved_event, actor = max(matches, key=lambda item: item[0])
            return await self.handle_actor_event(
                guild,
                actor,
                event=resolved_event,
                config=config,
            )
        actor = await self.find_executor(
            guild,
            event=event,
            target_id=target_id,
            channel_id=channel_id,
        )
        if actor is None:
            return False
        return await self.handle_actor_event(
            guild,
            actor,
            event=event,
            config=config,
        )

    async def handle_mass_mention(self, message: discord.Message) -> bool:
        guild = message.guild
        actor = message.author
        if guild is None or not isinstance(actor, discord.Member) or actor.bot:
            return False
        mention_count = len(message.mentions) + len(message.role_mentions)
        if not message.mention_everyone and mention_count < 2:
            return False
        config = await self.repository.get_security_config(guild.id)
        if not config.enabled:
            return False
        if not message.mention_everyone and mention_count < config.mention_limit:
            return False
        return await self.handle_actor_event(
            guild,
            actor,
            event="mass_mention",
            config=config,
            immediate=True,
        )

    async def _is_protected(
        self,
        guild: discord.Guild,
        actor: discord.User | discord.Member,
    ) -> bool:
        bot_user = self.bot.user
        if actor.id == guild.owner_id or (bot_user is not None and actor.id == bot_user.id):
            return True
        owner_check = getattr(self.bot, "is_owner", None)
        if callable(owner_check):
            try:
                if await owner_check(actor):
                    return True
            except (discord.HTTPException, TypeError):
                logger.exception("Configured bot-owner lookup failed.")
                return True
        try:
            return await self.repository.is_security_trusted(
                guild_id=guild.id,
                user_id=actor.id,
            )
        except Exception:
            logger.exception("Could not read the security trust list for guild %s.", guild.id)
            return True

    async def handle_actor_event(
        self,
        guild: discord.Guild,
        actor: discord.User | discord.Member,
        *,
        event: str,
        config: SecurityConfig | None = None,
        immediate: bool = False,
    ) -> bool:
        if actor is None or event not in _EVENT_LABELS:
            return False
        settings = config or await self.repository.get_security_config(guild.id)
        if not settings.enabled or await self._is_protected(guild, actor):
            return False

        now = time.monotonic()
        count = self.record_event(
            guild_id=guild.id,
            actor_id=actor.id,
            window_seconds=settings.window_seconds,
            now=now,
        )
        if (
            (not immediate and count < settings.threshold)
            or not self._should_alert(guild.id, actor.id, now)
        ):
            return False

        label = _EVENT_LABELS[event]
        alert = (
            f"⚠️ AEGIS security alert: {actor.mention} triggered {count} protected actions "
            f"({label}) within {settings.window_seconds} seconds. "
            f"Configured action: `{settings.action}`."
        )
        await self._send_alert(guild, settings, alert)
        if settings.action == "kick":
            outcome = await self._kick_actor(guild, actor, event)
            await self._send_alert(guild, settings, outcome)
        return True

    async def _send_alert(
        self,
        guild: discord.Guild,
        config: SecurityConfig,
        message: str,
    ) -> None:
        logger.warning("Security alert in guild %s: %s", guild.id, message)
        if config.log_channel_id is None:
            return
        channel = guild.get_channel(config.log_channel_id)
        if channel is None:
            logger.warning(
                "Configured security log channel %s is unavailable in guild %s.",
                config.log_channel_id,
                guild.id,
            )
            return
        try:
            await channel.send(
                message[:1900],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.warning("Security alert could not be delivered in guild %s.", guild.id)

    async def _kick_actor(
        self,
        guild: discord.Guild,
        actor: discord.User | discord.Member,
        event: str,
    ) -> str:
        member = actor if isinstance(actor, discord.Member) else guild.get_member(actor.id)
        if member is None:
            return "No kick was performed: the actor is no longer in the server."
        if member.id == guild.owner_id:
            return "No kick was performed: the server owner is protected."
        bot_member = guild.me
        if bot_member is None and self.bot.user is not None:
            try:
                bot_member = await guild.fetch_member(self.bot.user.id)
            except discord.HTTPException:
                bot_member = None
        if bot_member is None or not bot_member.guild_permissions.kick_members:
            return "No kick was performed: AEGIS lacks Kick Members permission."
        if member.top_role >= bot_member.top_role:
            return "No kick was performed: the actor's highest role is above AEGIS."
        try:
            await member.kick(reason=f"AEGIS security threshold: {event}"[:500])
        except discord.Forbidden:
            return "The configured kick was blocked by Discord permissions."
        except discord.HTTPException:
            return "The configured kick failed because Discord returned an error."
        return f"AEGIS kicked {member.mention} after the configured security threshold."
