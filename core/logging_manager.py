"""Persistent event logging with per-event and ignore-filter controls."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord

from database.repositories.community import CommunityRepository, LoggingConfig


logger = logging.getLogger(__name__)
EVENT_LABELS = {
    "message_edit": "Message edits",
    "message_delete": "Message deletions",
    "member_join": "Member joins",
    "member_leave": "Member leaves",
    "kick": "Kicks",
    "ban": "Bans",
    "unban": "Unbans",
    "timeout": "Timeout changes",
    "nickname_update": "Nickname changes",
    "member_role_update": "Member role changes",
    "channel_create": "Channel creation",
    "channel_delete": "Channel deletion",
    "channel_update": "Channel changes",
    "role_create": "Role creation",
    "role_delete": "Role deletion",
    "role_update": "Role changes",
    "voice_join": "Voice joins",
    "voice_leave": "Voice leaves",
    "voice_move": "Voice moves",
}
DEFAULT_LOGGING_EVENTS = tuple(EVENT_LABELS)


class LoggingManager:
    def __init__(
        self,
        bot: discord.Client,
        repository: CommunityRepository,
    ) -> None:
        self.bot = bot
        self.repository = repository

    @staticmethod
    def should_log(
        config: LoggingConfig | None,
        event: str,
        *,
        channel_ids: tuple[int, ...] = (),
        user_ids: tuple[int, ...] = (),
        role_ids: tuple[int, ...] = (),
    ) -> bool:
        if config is None or not config.enabled or event not in config.enabled_events:
            return False
        if set(channel_ids).intersection(config.ignored_channels):
            return False
        if set(user_ids).intersection(config.ignored_users):
            return False
        if set(role_ids).intersection(config.ignored_roles):
            return False
        return True

    async def send(
        self,
        *,
        guild: discord.Guild,
        event: str,
        content: str,
        channel_ids: tuple[int, ...] = (),
        user_ids: tuple[int, ...] = (),
        role_ids: tuple[int, ...] = (),
    ) -> bool:
        if event not in EVENT_LABELS:
            return False
        config = await self.repository.get_logging_config(guild.id)
        if not self.should_log(
            config,
            event,
            channel_ids=channel_ids,
            user_ids=user_ids,
            role_ids=role_ids,
        ):
            return False
        channel = guild.get_channel(config.channel_id)
        if channel is None:
            return False
        await channel.send(
            content[:2000],
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    async def find_executor(
        self,
        guild: discord.Guild,
        *,
        action: discord.AuditLogAction,
        target_id: int,
        max_age_seconds: int = 15,
    ) -> discord.User | discord.Member | None:
        bot_member = guild.me
        permissions = getattr(bot_member, "guild_permissions", None)
        if not bool(getattr(permissions, "view_audit_log", False)):
            return None
        cutoff = datetime.now(timezone.utc)
        try:
            async for entry in guild.audit_logs(limit=8, action=action):
                target = getattr(entry, "target", None)
                created_at = getattr(entry, "created_at", None)
                if getattr(target, "id", None) != target_id or created_at is None:
                    continue
                age = (cutoff - created_at).total_seconds()
                if 0 <= age <= max_age_seconds:
                    return getattr(entry, "user", None)
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("Audit-log lookup unavailable in guild %s.", guild.id)
        return None
