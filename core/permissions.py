"""Permission and target validation shared by moderation services."""

from __future__ import annotations


class ModerationPermissionError(PermissionError):
    """Raised when a moderator or the bot lacks the required permission."""


class ModerationTargetError(ValueError):
    """Raised when a moderation target is invalid or protected."""


def _role_position(member: object) -> int:
    role = getattr(member, "top_role", None)
    return int(getattr(role, "position", 0))


def _has_permission(member: object, permission: str) -> bool:
    permissions = getattr(member, "guild_permissions", None)
    return bool(getattr(permissions, permission, False))


def _require_same_guild(guild: object, member: object, label: str) -> None:
    member_guild = getattr(member, "guild", None)
    if member_guild is None or getattr(member_guild, "id", None) != getattr(guild, "id", None):
        raise ModerationTargetError(f"The {label} must belong to this server.")


def _require_moderator(guild: object, moderator: object, permission: str) -> None:
    if getattr(moderator, "bot", False):
        raise ModerationPermissionError("Bots cannot use this moderation command.")
    if getattr(moderator, "id", None) == getattr(guild, "owner_id", None):
        return
    if not _has_permission(moderator, permission):
        label = permission.replace("_", " ").title()
        raise ModerationPermissionError(f"You need the {label} permission.")


def _require_bot_permission(bot_member: object, permission: str) -> None:
    if not _has_permission(bot_member, permission):
        label = permission.replace("_", " ").title()
        raise ModerationPermissionError(f"The bot needs the {label} permission.")


def _validate_member_target(
    guild: object,
    target: object,
    moderator: object,
    bot_member: object,
    *,
    permission: str,
    action: str,
) -> None:
    """Validate member moderation permissions, target safety, and hierarchy."""
    _require_same_guild(guild, target, "target")
    _require_same_guild(guild, moderator, "moderator")
    _require_same_guild(guild, bot_member, "bot")
    _require_moderator(guild, moderator, permission)
    _require_bot_permission(bot_member, permission)

    target_id = getattr(target, "id", None)
    moderator_id = getattr(moderator, "id", None)
    bot_id = getattr(bot_member, "id", None)
    if target_id == moderator_id:
        action_label = {
            "voicemute": "voice-mute",
            "voiceunmute": "voice-unmute",
        }.get(action, action)
        raise ModerationTargetError(f"You cannot {action_label} yourself.")
    if target_id == bot_id:
        action_label = {
            "voicemute": "voice-mute",
            "voiceunmute": "voice-unmute",
        }.get(action, action)
        raise ModerationTargetError(f"The bot cannot {action_label} itself.")
    if target_id == getattr(guild, "owner_id", None):
        participles = {
            "ban": "banned",
            "kick": "kicked",
            "timeout": "timed out",
            "voicemute": "voice-muted",
            "voiceunmute": "voice-unmuted",
            "deafen": "deafened",
            "undeafen": "undeafened",
            "disconnect": "disconnected",
            "move": "moved",
        }
        participle = participles.get(action, f"{action}ed")
        raise ModerationTargetError(f"The server owner cannot be {participle}.")

    if moderator_id != getattr(guild, "owner_id", None):
        if _role_position(target) >= _role_position(moderator):
            raise ModerationTargetError(
                f"You cannot {action} a member with an equal or higher role."
            )
    if _role_position(target) >= _role_position(bot_member):
        raise ModerationTargetError(
            f"The bot cannot {action} a member with an equal or higher role."
        )


def validate_ban_target(
    guild: object,
    target: object,
    moderator: object,
    bot_member: object,
) -> None:
    """Validate ban permissions, membership, protected users, and hierarchy."""
    _validate_member_target(
        guild, target, moderator, bot_member, permission="ban_members", action="ban"
    )


def validate_kick_target(
    guild: object,
    target: object,
    moderator: object,
    bot_member: object,
) -> None:
    """Validate kick permissions, membership, protected users, and hierarchy."""
    _validate_member_target(
        guild, target, moderator, bot_member, permission="kick_members", action="kick"
    )


def validate_timeout_target(
    guild: object,
    target: object,
    moderator: object,
    bot_member: object,
) -> None:
    """Validate timeout permissions, membership, protected users, and hierarchy."""
    _validate_member_target(
        guild,
        target,
        moderator,
        bot_member,
        permission="moderate_members",
        action="timeout",
    )


def validate_voice_target(
    guild: object,
    target: object,
    moderator: object,
    bot_member: object,
    *,
    action: str,
) -> None:
    """Validate voice moderation/movement permission and target hierarchy."""
    if action not in {
        "voicemute", "voiceunmute", "deafen", "undeafen", "disconnect", "move"
    }:
        raise ValueError("Unsupported voice moderation action.")
    if action in {"deafen", "undeafen"}:
        permission = "deafen_members"
    elif action in {"disconnect", "move"}:
        permission = "move_members"
    else:
        permission = "mute_members"
    _validate_member_target(
        guild,
        target,
        moderator,
        bot_member,
        permission=permission,
        action=action,
    )


def validate_warning_target(
    guild: object,
    target: object,
    moderator: object,
) -> None:
    """Validate a warning target and the moderator's Manage Messages permission."""
    _require_same_guild(guild, target, "target")
    _require_same_guild(guild, moderator, "moderator")
    _require_moderator(guild, moderator, "manage_messages")
    if getattr(target, "bot", False):
        raise ModerationTargetError("Bot accounts cannot receive warnings.")
    if getattr(target, "id", None) == getattr(moderator, "id", None):
        raise ModerationTargetError("You cannot warn yourself.")
    if getattr(target, "id", None) == getattr(guild, "owner_id", None):
        raise ModerationTargetError("The server owner cannot be warned.")
    if getattr(moderator, "id", None) != getattr(guild, "owner_id", None):
        if _role_position(target) >= _role_position(moderator):
            raise ModerationTargetError(
                "You cannot warn a member with an equal or higher role."
            )


def validate_unban_target(
    guild: object,
    target_id: int,
    moderator: object,
    bot_member: object,
) -> None:
    """Validate unban permissions and protected IDs where role checks do not apply."""
    _require_same_guild(guild, moderator, "moderator")
    _require_same_guild(guild, bot_member, "bot")
    _require_moderator(guild, moderator, "ban_members")
    _require_bot_permission(bot_member, "ban_members")

    if not isinstance(target_id, int) or target_id <= 0:
        raise ModerationTargetError("Provide a valid Discord user ID.")
    if target_id == getattr(moderator, "id", None):
        raise ModerationTargetError("You cannot unban yourself.")
    if target_id == getattr(bot_member, "id", None):
        raise ModerationTargetError("The bot cannot unban itself.")
    if target_id == getattr(guild, "owner_id", None):
        raise ModerationTargetError("The server owner is not a valid unban target.")
