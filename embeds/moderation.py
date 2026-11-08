"""Reusable moderation embed designs; this module performs no moderation actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import discord

from core.embed_manager import embed_manager
from database.repositories.moderation import ModerationWarning, WarningStats


SUCCESS_COLOR = discord.Color(0x2ECC71)
WARNING_COLOR = discord.Color(0xF1C40F)
ERROR_COLOR = discord.Color(0xE74C3C)
SAMPLE_USER = "<@111111111111111111>"
PURGE_COMMANDS = {
    "purge", "purgeuser", "purgebots", "purgehumans", "purgelinks",
    "purgeinvites", "purgeimages", "purgefiles", "purgeembeds",
    "purgementions", "purgecontains", "purgeafter",
}


@dataclass(frozen=True)
class CommandPreviewSpec:
    usage: str
    success_title: str
    success_description: str = ""
    emoji_name: str = "success"
    confirmation_title: str | None = None
    confirmation_description: str | None = None


COMMAND_SPECS: dict[str, CommandPreviewSpec] = {
    "ban": CommandPreviewSpec("a!ban <user> [reason]", f"Banned {SAMPLE_USER}", "> Reason: Breaking rules"),
    "unban": CommandPreviewSpec("a!unban <user_id> [reason]", "Unbanned user Rexx", "> Reason: Appeal accepted"),
    "softban": CommandPreviewSpec("a!softban <user> [reason]", f"Softbanned {SAMPLE_USER}", "> Reason: Rule violation"),
    "tempban": CommandPreviewSpec("a!tempban <user> <duration> [reason]", f"Temporarily banned {SAMPLE_USER}", "> Duration: 1 day\n> Reason: Repeated spam"),
    "kick": CommandPreviewSpec("a!kick <user> [reason]", f"Kicked {SAMPLE_USER}", "> Reason: Rule violation"),
    "massban": CommandPreviewSpec(
        "a!massban <user_ids...> [reason]",
        "Banned 5 members",
        "> Reason: Coordinated raid",
        confirmation_title="Are you sure you want to ban these members?",
        confirmation_description="You are about to ban 5 members.",
    ),
    "masskick": CommandPreviewSpec(
        "a!masskick <users...> [reason]",
        "Kicked 5 members",
        "> Reason: Coordinated disruption",
        confirmation_title="Are you sure you want to kick these members?",
        confirmation_description="You are about to kick 5 members.",
    ),
    "timeout": CommandPreviewSpec("a!timeout <user> <duration> [reason]", f"Timed out {SAMPLE_USER}", "> Duration: 10 minutes\n> Reason: Spamming"),
    "untimeout": CommandPreviewSpec("a!untimeout <user> [reason]", f"Removed timeout from {SAMPLE_USER}", "> Reason: Reviewed"),
    "mute": CommandPreviewSpec("a!mute <user> <duration> [reason]", f"Muted {SAMPLE_USER}", "> Duration: 10 minutes\n> Reason: Spamming"),
    "unmute": CommandPreviewSpec("a!unmute <user> [reason]", f"Unmuted {SAMPLE_USER}", "> Reason: Reviewed"),
    "voicemute": CommandPreviewSpec("a!voicemute <user> [reason]", f"Muted {SAMPLE_USER} in voice", "> Reason: Disrupting voice chat", "success"),
    "voiceunmute": CommandPreviewSpec("a!voiceunmute <user> [reason]", f"Unmuted {SAMPLE_USER} in voice", "> Reason: Reviewed", "success"),
    "deafen": CommandPreviewSpec("a!deafen <user> [reason]", f"Deafened {SAMPLE_USER}", "> Reason: Disrupting voice chat", "success"),
    "undeafen": CommandPreviewSpec("a!undeafen <user> [reason]", f"Undeafened {SAMPLE_USER}", "> Reason: Reviewed", "success"),
    "disconnect": CommandPreviewSpec("a!disconnect <user> [reason]", f"Disconnected {SAMPLE_USER} from voice", "> Reason: Disrupting voice chat", "success"),
    "move": CommandPreviewSpec("a!move <user> <voice_channel>", f"Moved {SAMPLE_USER} to #lobby", "> From: #general-voice", "success"),
    "warn": CommandPreviewSpec("a!warn <user> <reason>", f"Warned {SAMPLE_USER}", "> Reason: Spamming"),
    "unwarn": CommandPreviewSpec("a!unwarn <user> <warning_id>", f"Removed a warning for {SAMPLE_USER}", "> Case: #104"),
    "warnings": CommandPreviewSpec("a!warnings <user>", f"Warnings for {SAMPLE_USER}", "> Active warnings: 2\n> Latest case: #104", "moderation"),
    "clearwarnings": CommandPreviewSpec(
        "a!clearwarnings <user>",
        f"Cleared warnings for {SAMPLE_USER}",
        "> Warnings removed: 2",
        confirmation_title="Are you sure you want to clear these warnings?",
        confirmation_description=f"You are about to clear all warnings for {SAMPLE_USER}.",
    ),
    "warninfo": CommandPreviewSpec("a!warninfo <warning_id>", "Warning #104", "> User: @Rexx\n> Reason: Spamming\n> Moderator: @Moderator", "moderation"),
    "warnlist": CommandPreviewSpec("a!warnlist [user]", f"Warning list for {SAMPLE_USER}", "> Active warnings: 2\n> Page: 1 of 1", "moderation"),
    "warnstats": CommandPreviewSpec("a!warnstats", "Warning statistics", "> Active warnings: 12\n> Members warned: 8", "moderation"),
    "purge": CommandPreviewSpec(
        "a!purge <count>",
        "Deleted 50 messages",
        "",
        "delete",
        "Are you sure you want to delete matching messages?",
        "You are about to delete 50 matching messages.",
    ),
    "purgeuser": CommandPreviewSpec("a!purgeuser <user> <count>", f"Deleted 25 messages from {SAMPLE_USER}", "", "delete", "Are you sure you want to delete this user's messages?", f"You are about to delete 25 messages from {SAMPLE_USER}."),
    "purgebots": CommandPreviewSpec("a!purgebots <count>", "Deleted 20 bot messages", "", "delete", "Are you sure you want to delete bot messages?", "You are about to delete 20 bot messages."),
    "purgehumans": CommandPreviewSpec("a!purgehumans <count>", "Deleted 20 human messages", "", "delete", "Are you sure you want to delete human messages?", "You are about to delete 20 human messages."),
    "purgelinks": CommandPreviewSpec("a!purgelinks <count>", "Deleted 10 messages containing links", "", "delete", "Are you sure you want to delete messages with links?", "You are about to delete 10 messages containing links."),
    "purgeinvites": CommandPreviewSpec("a!purgeinvites <count>", "Deleted 10 messages containing invites", "", "delete", "Are you sure you want to delete messages with invites?", "You are about to delete 10 messages containing invites."),
    "purgeimages": CommandPreviewSpec("a!purgeimages <count>", "Deleted 15 messages containing images", "", "delete", "Are you sure you want to delete messages with images?", "You are about to delete 15 messages containing images."),
    "purgefiles": CommandPreviewSpec("a!purgefiles <count>", "Deleted 10 messages containing files", "", "delete", "Are you sure you want to delete messages with files?", "You are about to delete 10 messages containing files."),
    "purgeembeds": CommandPreviewSpec("a!purgeembeds <count>", "Deleted 10 messages containing embeds", "", "delete", "Are you sure you want to delete messages with embeds?", "You are about to delete 10 messages containing embeds."),
    "purgementions": CommandPreviewSpec("a!purgementions <count>", "Deleted 10 messages containing mentions", "", "delete", "Are you sure you want to delete messages with mentions?", "You are about to delete 10 messages containing mentions."),
    "purgecontains": CommandPreviewSpec("a!purgecontains <text> <count>", 'Deleted 10 messages containing "spam"', "", "delete", "Are you sure you want to delete matching messages?", 'You are about to delete 10 messages containing "spam".'),
    "purgeafter": CommandPreviewSpec("a!purgeafter <message_id>", "Deleted 18 messages after the selected message", "", "delete", "Are you sure you want to delete later messages?", "You are about to delete 18 messages after the selected message."),
    "lock": CommandPreviewSpec("a!lock [channel] [reason]", "Locked #general", "> Reason: Scheduled maintenance"),
    "unlock": CommandPreviewSpec("a!unlock [channel] [reason]", "Unlocked #general", "> Reason: Maintenance complete"),
    "lockall": CommandPreviewSpec(
        "a!lockall",
        "Locked 12 text channels",
        "",
        confirmation_title="Are you sure you want to lock every text channel?",
        confirmation_description="You are about to lock 12 text channels.",
    ),
    "unlockall": CommandPreviewSpec(
        "a!unlockall",
        "Unlocked 12 text channels",
        "",
        confirmation_title="Are you sure you want to unlock every text channel?",
        confirmation_description="You are about to unlock 12 text channels.",
    ),
    "slowmode": CommandPreviewSpec("a!slowmode <seconds> [channel]", "Set slowmode to 10 seconds in #general", ""),
    "nick": CommandPreviewSpec("a!nick <user> <nickname>", f"Changed {SAMPLE_USER}'s nickname", "> New nickname: Rexx"),
    "resetnick": CommandPreviewSpec("a!resetnick <user>", f"Reset {SAMPLE_USER}'s nickname", "> Display name restored"),
    "jail": CommandPreviewSpec("a!jail <user> [reason]", f"Jailed {SAMPLE_USER}", "> Reason: Repeated rule violations"),
    "unjail": CommandPreviewSpec("a!unjail <user> [reason]", f"Unjailed {SAMPLE_USER}", "> Previous roles restored: 3"),
}


def _get_spec(command_name: str) -> CommandPreviewSpec:
    try:
        return COMMAND_SPECS[command_name]
    except KeyError as exc:
        raise ValueError(f"Unknown moderation command: {command_name}") from exc


def success_embed(
    command_name: str,
    *,
    target: discord.abc.User | None = None,
    reason: str | None = None,
    duration: str | None = None,
    count: int | None = None,
    total: int | None = None,
    warning_id: int | None = None,
    source_channel: discord.abc.GuildChannel | None = None,
    destination_channel: discord.abc.GuildChannel | None = None,
    channel: discord.abc.GuildChannel | None = None,
    nickname: str | None = None,
    seconds: int | None = None,
    restored_count: int | None = None,
    skipped_count: int = 0,
    match_text: str | None = None,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    """Build the designed success embed for one registered command."""
    spec = _get_spec(command_name)
    title = spec.success_title
    description = spec.success_description
    if target is not None:
        mention = target.mention
        title = title.replace(SAMPLE_USER, mention).replace("Rexx", mention)
    if reason is not None and description:
        safe_reason = discord.utils.escape_mentions(reason)
        if "> Reason: " in description:
            description = description.rsplit("> Reason: ", 1)[0] + f"> Reason: {safe_reason}"
        elif command_name in {"ban", "unban"}:
            description = f"> Reason: {safe_reason}"
    if duration is not None and description:
        lines = description.splitlines()
        for index, line in enumerate(lines):
            if line.startswith("> Duration: "):
                lines[index] = f"> Duration: {duration}"
                break
        description = "\n".join(lines)
    if count is not None and command_name in {"massban", "masskick"}:
        if total is not None and count < total:
            title = title.replace("5 members", f"{count} of {total} members")
        else:
            title = title.replace("5 members", f"{count} members")
    if count is not None and command_name in PURGE_COMMANDS:
        if command_name == "purge":
            title = f"Deleted {count} messages"
        elif command_name == "purgeuser":
            user_label = target.mention if target is not None else "the selected user"
            title = f"Deleted {count} messages from {user_label}"
        elif command_name == "purgebots":
            title = f"Deleted {count} bot messages"
        elif command_name == "purgehumans":
            title = f"Deleted {count} human messages"
        elif command_name == "purgeinvites":
            title = f"Deleted {count} messages containing Discord invites"
        elif command_name == "purgeimages":
            title = f"Deleted {count} messages containing images"
        elif command_name == "purgefiles":
            title = f"Deleted {count} messages containing files"
        elif command_name == "purgeembeds":
            title = f"Deleted {count} messages containing embeds"
        elif command_name == "purgementions":
            title = f"Deleted {count} messages containing mentions"
        elif command_name == "purgecontains":
            label = discord.utils.escape_mentions(match_text or "the selected text")
            title = f"Deleted {count} messages containing “{label}”"
        elif command_name == "purgeafter":
            title = f"Deleted {count} messages after the selected message"
        else:
            title = f"Deleted {count} messages containing links"
    if command_name == "unwarn" and warning_id is not None:
        description = f"> Warning removed: #{warning_id}"
    elif command_name == "warn" and warning_id is not None and description:
        description += f"\n> Warning: #{warning_id}"
    elif command_name == "clearwarnings" and count is not None:
        description = f"> Warnings removed: {count}"
    elif command_name == "move":
        from_label = source_channel.mention if source_channel is not None else "Unknown"
        to_label = (
            destination_channel.mention if destination_channel is not None else "#channel"
        )
        description = f"> From: {from_label}\n> To: {to_label}"
        if reason is not None:
            description += f"\n> Reason: {discord.utils.escape_mentions(reason)}"
    if command_name in {"lock", "unlock"} and channel is not None:
        verb = "Locked" if command_name == "lock" else "Unlocked"
        title = f"{verb} {channel.mention}"
    elif command_name in {"lockall", "unlockall"} and count is not None:
        verb = "Locked" if command_name == "lockall" else "Unlocked"
        title = f"{verb} {count} text channels"
        if skipped_count:
            description = f"> Skipped: {skipped_count} channel(s)"
    elif command_name == "slowmode" and channel is not None and seconds is not None:
        setting = "disabled" if seconds == 0 else f"set to {seconds} second(s)"
        title = f"Slowmode {setting} in {channel.mention}"
    elif command_name == "nick" and target is not None:
        title = f"Changed {target.mention}'s nickname"
        description = f"> New nickname: {discord.utils.escape_mentions(nickname or '')}"
    elif command_name == "resetnick" and target is not None:
        title = f"Reset {target.mention}'s nickname"
        description = "> Display name restored"
    elif command_name == "jail" and target is not None:
        title = f"Jailed {target.mention}"
    elif command_name == "unjail" and target is not None:
        title = f"Unjailed {target.mention}"
        description = f"> Previous roles restored: {restored_count or 0}"
        if skipped_count:
            description += f"\n> Roles skipped: {skipped_count}"
    return embed_manager.action(
        message=title,
        details=description,
        emoji_names=("success",),
        color=SUCCESS_COLOR,
    )


def confirmation_embed(
    command_name: str,
    *,
    count: int | None = None,
    target: discord.abc.User | None = None,
    guild: discord.Guild | None = None,
    match_text: str | None = None,
) -> discord.Embed:
    """Build a warning embed for an action that requires confirmation."""
    spec = _get_spec(command_name)
    if spec.confirmation_title is None or spec.confirmation_description is None:
        raise ValueError(f"{command_name} does not require a confirmation preview")
    description = spec.confirmation_description
    if count is not None and command_name == "massban":
        description = f"You are about to ban {count} members."
    elif count is not None and command_name == "masskick":
        description = f"You are about to kick {count} members."
    elif count is not None and command_name == "clearwarnings":
        target_label = target.mention if target is not None else SAMPLE_USER
        description = (
            f"You are about to permanently remove {count} warning(s) from {target_label}."
        )
    elif count is not None and command_name in PURGE_COMMANDS:
        if command_name == "purgeuser":
            target_label = target.mention if target is not None else "the selected user"
            description = f"You are about to delete {count} messages from {target_label}."
        elif command_name == "purgebots":
            description = f"You are about to delete {count} bot messages."
        elif command_name == "purgehumans":
            description = f"You are about to delete {count} human messages."
        elif command_name == "purgelinks":
            description = f"You are about to delete {count} messages containing links."
        elif command_name == "purgeinvites":
            description = f"You are about to delete {count} messages containing Discord invites."
        elif command_name == "purgeimages":
            description = f"You are about to delete {count} messages containing images."
        elif command_name == "purgefiles":
            description = f"You are about to delete {count} messages containing files."
        elif command_name == "purgeembeds":
            description = f"You are about to delete {count} messages containing embeds."
        elif command_name == "purgementions":
            description = f"You are about to delete {count} messages containing mentions."
        elif command_name == "purgeafter":
            description = f"You are about to delete {count} messages after the selected message."
        elif command_name == "purgecontains":
            label = discord.utils.escape_mentions(match_text or "the selected text")
            description = (
                f"You are about to delete {count} messages containing "
                f"“{label[:120]}”."
            )
        elif command_name == "lockall":
            description = f"You are about to lock {count} text channels."
        elif command_name == "unlockall":
            description = f"You are about to restore send permissions in {count} text channels."
        else:
            description = f"You are about to delete {count} matching messages."
    if target is not None:
        description = description.replace(SAMPLE_USER, target.mention)
    return embed_manager.action(
        message=spec.confirmation_title,
        details=description,
        emoji_names=("warning",),
        color=WARNING_COLOR,
    )


def warning_history_embeds(
    target: discord.abc.User,
    warnings: list[ModerationWarning],
    *,
    page_size: int = 8,
    guild: discord.Guild | None = None,
) -> list[discord.Embed]:
    """Build bounded, themed pages containing the target's complete warning history."""
    if page_size < 1 or page_size > 10:
        raise ValueError("Warning history page size must be between 1 and 10.")
    page_count = max(1, (len(warnings) + page_size - 1) // page_size)
    spec = _get_spec("warnings")
    title = spec.success_title.replace(SAMPLE_USER, target.mention)
    embeds: list[discord.Embed] = []
    for page_index in range(page_count):
        page_warnings = warnings[page_index * page_size : (page_index + 1) * page_size]
        description = (
            f"> Active warnings: {len(warnings)}\n> Page: {page_index + 1} of {page_count}"
        )
        if not warnings:
            description += "\n\nNo active warnings."
        embed = embed_manager.titled(
            title=title,
            description=description,
            emoji_names=("moderation",),
            color=SUCCESS_COLOR,
        )
        for warning in page_warnings:
            created_at = datetime.fromisoformat(warning.created_at)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            timestamp = int(created_at.timestamp())
            reason = discord.utils.escape_mentions(warning.reason)
            embed.add_field(
                name=f"Warning #{warning.warning_id} · <t:{timestamp}:R>",
                value=f"Moderator: **<@{warning.moderator_id}>**\nReason: {reason}",
                inline=False,
            )
        embeds.append(embed)
    return embeds


def warning_list_embed(
    warnings: list[ModerationWarning],
    *,
    total: int,
    page: int,
    page_size: int,
    target: discord.abc.User | None = None,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    """Build one bounded server or member warning-list page."""
    page_count = max(1, (total + page_size - 1) // page_size)
    if not 1 <= page <= page_count:
        raise ValueError("Warning list page is outside the available range.")
    target_label = f" for {target.mention}" if target is not None else " in this server"
    description = f"> Total warnings: {total}\n> Page: {page} of {page_count}"
    if not warnings:
        description += "\n\nNo warnings found."
    embed = embed_manager.titled(
        title=f"Warning list{target_label}",
        description=description,
        emoji_names=("moderation",),
        color=SUCCESS_COLOR,
    )
    for warning in warnings:
        created_at = datetime.fromisoformat(warning.created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        timestamp = int(created_at.timestamp())
        reason = discord.utils.escape_mentions(warning.reason)
        embed.add_field(
            name=f"Warning #{warning.warning_id} · <t:{timestamp}:R>",
            value=(
                f"User: **<@{warning.target_id}>**\n"
                f"Moderator: **<@{warning.moderator_id}>**\n"
                f"Reason: {reason}"
            ),
            inline=False,
        )
    return embed


def warning_stats_embed(
    stats: WarningStats, *, guild: discord.Guild | None = None
) -> discord.Embed:
    """Build warning statistics from the repository's stored totals."""
    return embed_manager.titled(
        title="Warning statistics",
        description=(
            f"> Total warnings: {stats.total_warnings}\n"
            f"> Members warned: {stats.members_warned}\n"
            f"> Moderators with warnings: {stats.moderators_with_warnings}"
        ),
        emoji_names=("moderation",),
        color=SUCCESS_COLOR,
    )


def warning_info_embed(
    warning: ModerationWarning, *, guild: discord.Guild | None = None
) -> discord.Embed:
    """Build the complete details view for one guild-scoped warning."""
    created_at = datetime.fromisoformat(warning.created_at)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    timestamp = int(created_at.timestamp())
    embed = embed_manager.titled(
        title=f"Warning #{warning.warning_id}",
        emoji_names=("moderation",),
        color=WARNING_COLOR,
    )
    embed.add_field(name="Target user", value=f"**<@{warning.target_id}>**", inline=True)
    embed.add_field(name="Moderator", value=f"**<@{warning.moderator_id}>**", inline=True)
    embed.add_field(
        name="Timestamp",
        value=f"<t:{timestamp}:F> (<t:{timestamp}:R>)",
        inline=False,
    )
    embed.add_field(
        name="Reason",
        value=discord.utils.escape_mentions(warning.reason) or "No reason provided.",
        inline=False,
    )
    return embed
