"""Validated ban/unban operations and their persistent audit cases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord

from core.permissions import (
    ModerationPermissionError,
    ModerationTargetError,
    validate_ban_target,
    validate_kick_target,
    validate_timeout_target,
    validate_unban_target,
    validate_voice_target,
    validate_warning_moderator,
    validate_warning_target,
)
from database.repositories.moderation import (
    ModerationCase,
    ModerationRepository,
    ModerationWarning,
    WarningStats,
)


logger = logging.getLogger(__name__)


class ModerationServiceError(RuntimeError):
    """Base class for user-safe moderation service failures."""


@dataclass(frozen=True)
class BulkModerationResult:
    attempted: int
    completed_target_ids: tuple[int, ...]
    failed_target_ids: tuple[int, ...]


class AuditLogError(ModerationServiceError):
    """The Discord action ran, but its final audit status could not be saved."""

    def __init__(self, case_id: int, action_applied: bool) -> None:
        self.case_id = case_id
        self.action_applied = action_applied
        if action_applied:
            message = (
                f"A Discord action was applied, but case #{case_id} could not be finalized "
                "in the database. The case remains pending."
            )
        else:
            message = f"The action failed and case #{case_id} could not be updated."
        super().__init__(message)


def normalize_reason(reason: str | None) -> str:
    value = (reason or "").strip() or "No reason provided."
    if len(value) > 450:
        raise ModerationTargetError("The reason must be 450 characters or fewer.")
    return value


class ModerationService:
    def __init__(self, repository: ModerationRepository) -> None:
        self.repository = repository

    async def _mark_failed(self, case_id: int) -> None:
        try:
            await self.repository.update_case_status(case_id, "failed")
        except Exception:
            logger.exception("Could not mark moderation case %s as failed.", case_id)

    async def _mark_completed(self, case_id: int) -> None:
        try:
            await self.repository.update_case_status(case_id, "completed")
        except Exception as exc:
            raise AuditLogError(case_id, action_applied=True) from exc

    async def _mark_partial(self, case_id: int) -> None:
        try:
            await self.repository.update_case_status(case_id, "partial")
        except Exception as exc:
            raise AuditLogError(case_id, action_applied=True) from exc

    async def ban_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_ban_target(guild, target, moderator, bot_member)
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="ban",
            reason=normalized_reason,
        )
        audit_reason = f"Case #{case.case_id}: {normalized_reason}"[:512]
        try:
            await target.ban(reason=audit_reason, delete_message_seconds=0)
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def kick_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_kick_target(guild, target, moderator, bot_member)
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="kick",
            reason=normalized_reason,
        )
        audit_reason = f"Case #{case.case_id}: {normalized_reason}"[:512]
        try:
            await target.kick(reason=audit_reason)
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def massban_members(
        self,
        *,
        guild: discord.Guild,
        targets: list[discord.Member],
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
        max_targets: int = 10,
    ) -> BulkModerationResult:
        if not 2 <= len(targets) <= max_targets:
            raise ModerationTargetError(
                f"Massban must include between 2 and {max_targets} unique members."
            )
        target_ids = [target.id for target in targets]
        if len(set(target_ids)) != len(target_ids):
            raise ModerationTargetError("Massban targets must be unique.")
        for target in targets:
            validate_ban_target(guild, target, moderator, bot_member)

        normalized_reason = normalize_reason(reason)
        cases: list[ModerationCase] = []
        try:
            for target in targets:
                cases.append(
                    await self.repository.create_case(
                        guild_id=guild.id,
                        target_id=target.id,
                        moderator_id=moderator.id,
                        action_type="massban",
                        reason=normalized_reason,
                    )
                )
        except Exception:
            for case in cases:
                await self._mark_failed(case.case_id)
            raise

        completed: list[int] = []
        failed: list[int] = []
        for target, case in zip(targets, cases):
            try:
                await target.ban(
                    reason=f"Case #{case.case_id}: {normalized_reason}"[:512],
                    delete_message_seconds=0,
                )
            except Exception:
                await self._mark_failed(case.case_id)
                failed.append(target.id)
            else:
                await self._mark_completed(case.case_id)
                completed.append(target.id)
        return BulkModerationResult(
            attempted=len(targets),
            completed_target_ids=tuple(completed),
            failed_target_ids=tuple(failed),
        )

    async def masskick_members(
        self,
        *,
        guild: discord.Guild,
        targets: list[discord.Member],
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
        max_targets: int = 10,
    ) -> BulkModerationResult:
        if not 2 <= len(targets) <= max_targets:
            raise ModerationTargetError(
                f"Masskick must include between 2 and {max_targets} unique members."
            )
        target_ids = [target.id for target in targets]
        if len(set(target_ids)) != len(target_ids):
            raise ModerationTargetError("Masskick targets must be unique.")
        for target in targets:
            validate_kick_target(guild, target, moderator, bot_member)

        normalized_reason = normalize_reason(reason)
        cases: list[ModerationCase] = []
        try:
            for target in targets:
                cases.append(
                    await self.repository.create_case(
                        guild_id=guild.id,
                        target_id=target.id,
                        moderator_id=moderator.id,
                        action_type="masskick",
                        reason=normalized_reason,
                    )
                )
        except Exception:
            for case in cases:
                await self._mark_failed(case.case_id)
            raise

        completed: list[int] = []
        failed: list[int] = []
        for target, case in zip(targets, cases):
            try:
                await target.kick(reason=f"Case #{case.case_id}: {normalized_reason}"[:512])
            except Exception:
                await self._mark_failed(case.case_id)
                failed.append(target.id)
            else:
                await self._mark_completed(case.case_id)
                completed.append(target.id)
        return BulkModerationResult(
            attempted=len(targets),
            completed_target_ids=tuple(completed),
            failed_target_ids=tuple(failed),
        )

    async def timeout_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        duration: timedelta,
        reason: str | None = None,
        action_type: str = "timeout",
    ) -> ModerationCase:
        validate_timeout_target(guild, target, moderator, bot_member)
        if duration.total_seconds() <= 0 or duration > timedelta(days=28):
            raise ModerationTargetError("Timeout duration must be between 1 second and 28 days.")
        normalized_reason = normalize_reason(reason)
        expires_at = (datetime.now(timezone.utc) + duration).isoformat(timespec="seconds")
        if action_type not in {"timeout", "mute"}:
            raise ValueError("Invalid timeout action type.")
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type=action_type,
            reason=normalized_reason,
            expires_at=expires_at,
        )
        try:
            await target.timeout(
                duration,
                reason=f"Case #{case.case_id}: {normalized_reason}"[:512],
            )
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def untimeout_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
        action_type: str = "untimeout",
    ) -> ModerationCase:
        validate_timeout_target(guild, target, moderator, bot_member)
        if action_type not in {"untimeout", "unmute"}:
            raise ValueError("Invalid timeout removal action type.")
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type=action_type,
            reason=normalized_reason,
        )
        try:
            await target.timeout(
                None,
                reason=f"Case #{case.case_id}: {normalized_reason}"[:512],
            )
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def voicemute_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_voice_target(
            guild, target, moderator, bot_member, action="voicemute"
        )
        if target.voice is None or target.voice.channel is None:
            raise ModerationTargetError("The target must be connected to a voice channel.")
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="voicemute",
            reason=normalized_reason,
        )
        try:
            await target.edit(mute=True, reason=f"Case #{case.case_id}: {normalized_reason}"[:512])
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def voiceunmute_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_voice_target(
            guild, target, moderator, bot_member, action="voiceunmute"
        )
        if target.voice is None or target.voice.channel is None:
            raise ModerationTargetError("The target must be connected to a voice channel.")
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="voiceunmute",
            reason=normalized_reason,
        )
        try:
            await target.edit(
                mute=False,
                reason=f"Case #{case.case_id}: {normalized_reason}"[:512],
            )
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def deafen_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_voice_target(guild, target, moderator, bot_member, action="deafen")
        if target.voice is None or target.voice.channel is None:
            raise ModerationTargetError("The target must be connected to a voice channel.")
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="deafen",
            reason=normalized_reason,
        )
        try:
            await target.edit(
                deafen=True,
                reason=f"Case #{case.case_id}: {normalized_reason}"[:512],
            )
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def undeafen_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_voice_target(guild, target, moderator, bot_member, action="undeafen")
        if target.voice is None or target.voice.channel is None:
            raise ModerationTargetError("The target must be connected to a voice channel.")
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="undeafen",
            reason=normalized_reason,
        )
        try:
            await target.edit(
                deafen=False,
                reason=f"Case #{case.case_id}: {normalized_reason}"[:512],
            )
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def disconnect_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_voice_target(
            guild, target, moderator, bot_member, action="disconnect"
        )
        if target.voice is None or target.voice.channel is None:
            raise ModerationTargetError("The target must be connected to a voice channel.")
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="disconnect",
            reason=normalized_reason,
        )
        try:
            await target.move_to(
                None, reason=f"Case #{case.case_id}: {normalized_reason}"[:512]
            )
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def move_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        destination: discord.VoiceChannel | discord.StageChannel,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_voice_target(guild, target, moderator, bot_member, action="move")
        if target.voice is None or target.voice.channel is None:
            raise ModerationTargetError("The target must be connected to a voice channel.")
        destination_guild = getattr(destination, "guild", None)
        if getattr(destination_guild, "id", None) != guild.id:
            raise ModerationTargetError("The destination must be a voice channel in this server.")
        if getattr(destination, "type", None) not in {
            discord.ChannelType.voice,
            discord.ChannelType.stage_voice,
        }:
            raise ModerationTargetError("The destination must be a voice or stage channel.")
        if target.voice.channel.id == destination.id:
            raise ModerationTargetError("The target is already in that voice channel.")
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="move",
            reason=normalized_reason,
        )
        try:
            await target.move_to(
                destination, reason=f"Case #{case.case_id}: {normalized_reason}"[:512]
            )
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def warn_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        reason: str | None = None,
    ) -> ModerationWarning:
        validate_warning_target(guild, target, moderator)
        return await self.repository.create_warning(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            reason=normalize_reason(reason),
        )

    async def warnings_for_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
    ) -> list[ModerationWarning]:
        validate_warning_target(guild, target, moderator)
        return await self.repository.list_warnings(
            guild_id=guild.id, target_id=target.id
        )

    async def warning_page(
        self,
        *,
        guild: discord.Guild,
        moderator: discord.Member,
        target: discord.Member | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ModerationWarning], int]:
        if target is None:
            validate_warning_moderator(guild, moderator)
        else:
            validate_warning_target(guild, target, moderator)
        return await self.repository.list_warning_page(
            guild_id=guild.id,
            target_id=target.id if target is not None else None,
            limit=limit,
            offset=offset,
        )

    async def warning_statistics(
        self, *, guild: discord.Guild, moderator: discord.Member
    ) -> WarningStats:
        validate_warning_moderator(guild, moderator)
        return await self.repository.get_warning_stats(guild_id=guild.id)

    async def remove_warning(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        warning_id: int,
        moderator: discord.Member,
    ) -> ModerationWarning:
        validate_warning_target(guild, target, moderator)
        if warning_id <= 0:
            raise ModerationTargetError("Provide a valid warning ID.")
        warning = await self.repository.delete_warning(
            guild_id=guild.id,
            target_id=target.id,
            warning_id=warning_id,
        )
        if warning is None:
            raise ModerationTargetError(
                f"Warning #{warning_id} was not found for this member in this server."
            )
        return warning

    async def clear_warnings_for_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
    ) -> int:
        validate_warning_target(guild, target, moderator)
        return await self.repository.clear_warnings(
            guild_id=guild.id, target_id=target.id
        )

    async def softban_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        """Ban for seven-day message cleanup, then unban; log partial failures."""
        validate_ban_target(guild, target, moderator, bot_member)
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="softban",
            reason=normalized_reason,
        )
        audit_reason = f"Case #{case.case_id}: {normalized_reason}"[:512]
        try:
            await target.ban(reason=audit_reason, delete_message_seconds=7 * 24 * 60 * 60)
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        try:
            await guild.unban(
                discord.Object(id=target.id),
                reason=f"Softban completed for case #{case.case_id}",
            )
        except Exception as exc:
            await self._mark_partial(case.case_id)
            raise ModerationServiceError(
                f"Softban case #{case.case_id} applied the ban, but automatic unban failed."
            ) from exc
        await self._mark_completed(case.case_id)
        return case

    async def tempban_member(
        self,
        *,
        guild: discord.Guild,
        target: discord.Member,
        moderator: discord.Member,
        bot_member: discord.Member,
        duration: timedelta,
        reason: str | None = None,
    ) -> ModerationCase:
        """Ban a member until a persisted expiry time."""
        validate_ban_target(guild, target, moderator, bot_member)
        if duration.total_seconds() <= 0 or duration.total_seconds() > 365 * 24 * 60 * 60:
            raise ModerationTargetError("The duration must be between 1 second and 365 days.")
        normalized_reason = normalize_reason(reason)
        expires_at = (datetime.now(timezone.utc) + duration).isoformat(timespec="seconds")
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="tempban",
            reason=normalized_reason,
            expires_at=expires_at,
        )
        audit_reason = f"Case #{case.case_id}: {normalized_reason}"[:512]
        try:
            await target.ban(reason=audit_reason, delete_message_seconds=0)
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case

    async def unban_user(
        self,
        *,
        guild: discord.Guild,
        target: discord.User,
        moderator: discord.Member,
        bot_member: discord.Member,
        reason: str | None = None,
    ) -> ModerationCase:
        validate_unban_target(guild, target.id, moderator, bot_member)
        normalized_reason = normalize_reason(reason)
        case = await self.repository.create_case(
            guild_id=guild.id,
            target_id=target.id,
            moderator_id=moderator.id,
            action_type="unban",
            reason=normalized_reason,
        )
        audit_reason = f"Case #{case.case_id}: {normalized_reason}"[:512]
        try:
            await guild.unban(discord.Object(id=target.id), reason=audit_reason)
        except Exception:
            await self._mark_failed(case.case_id)
            raise
        await self._mark_completed(case.case_id)
        return case


__all__ = [
    "AuditLogError",
    "ModerationPermissionError",
    "ModerationService",
    "ModerationServiceError",
    "ModerationTargetError",
    "normalize_reason",
]
