"""Reusable moderation embed designs; this module performs no moderation actions."""

from __future__ import annotations

from dataclasses import dataclass

import discord

from core.emoji_manager import emoji_markup


SUCCESS_COLOR = discord.Color(0x2ECC71)
WARNING_COLOR = discord.Color(0xF1C40F)
ERROR_COLOR = discord.Color(0xE74C3C)
SAMPLE_USER = "<@111111111111111111>"


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
        confirmation_title="Confirm massban",
        confirmation_description="You are about to ban 5 members.",
    ),
    "masskick": CommandPreviewSpec(
        "a!masskick <users...> [reason]",
        "Kicked 5 members",
        "> Reason: Coordinated disruption",
        confirmation_title="Confirm masskick",
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
        confirmation_title="Confirm clearing warnings",
        confirmation_description=f"You are about to clear all warnings for {SAMPLE_USER}.",
    ),
    "warninfo": CommandPreviewSpec("a!warninfo <warning_id>", "Warning #104", "> User: @Rexx\n> Reason: Spamming\n> Moderator: @Moderator", "moderation"),
    "warnlist": CommandPreviewSpec("a!warnlist [user]", f"Warning list for {SAMPLE_USER}", "> Active warnings: 2\n> Page: 1 of 1", "moderation"),
    "warnstats": CommandPreviewSpec("a!warnstats", "Warning statistics", "> Active warnings: 12\n> Members warned: 8", "moderation"),
    "purge": CommandPreviewSpec(
        "a!purge <count>",
        "Successfully deleted 50 messages",
        "",
        "delete",
        "Confirm purge",
        "You are about to delete 50 matching messages.",
    ),
    "purgeuser": CommandPreviewSpec("a!purgeuser <user> <count>", f"Deleted 25 messages from {SAMPLE_USER}", "", "delete", "Confirm purgeuser", f"You are about to delete 25 messages from {SAMPLE_USER}."),
    "purgebots": CommandPreviewSpec("a!purgebots <count>", "Deleted 20 bot messages", "", "delete", "Confirm purgebots", "You are about to delete 20 bot messages."),
    "purgehumans": CommandPreviewSpec("a!purgehumans <count>", "Deleted 20 human messages", "", "delete", "Confirm purgehumans", "You are about to delete 20 human messages."),
    "purgelinks": CommandPreviewSpec("a!purgelinks <count>", "Deleted 10 messages containing links", "", "delete", "Confirm purgelinks", "You are about to delete 10 messages containing links."),
    "purgeinvites": CommandPreviewSpec("a!purgeinvites <count>", "Deleted 10 messages containing invites", "", "delete", "Confirm purgeinvites", "You are about to delete 10 messages containing invites."),
    "purgeimages": CommandPreviewSpec("a!purgeimages <count>", "Deleted 15 messages containing images", "", "delete", "Confirm purgeimages", "You are about to delete 15 messages containing images."),
    "purgefiles": CommandPreviewSpec("a!purgefiles <count>", "Deleted 10 messages containing files", "", "delete", "Confirm purgefiles", "You are about to delete 10 messages containing files."),
    "purgeembeds": CommandPreviewSpec("a!purgeembeds <count>", "Deleted 10 messages containing embeds", "", "delete", "Confirm purgeembeds", "You are about to delete 10 messages containing embeds."),
    "purgementions": CommandPreviewSpec("a!purgementions <count>", "Deleted 10 messages containing mentions", "", "delete", "Confirm purgementions", "You are about to delete 10 messages containing mentions."),
    "purgecontains": CommandPreviewSpec("a!purgecontains <text> <count>", 'Deleted 10 messages containing "spam"', "", "delete", "Confirm purgecontains", 'You are about to delete 10 messages containing "spam".'),
    "purgeafter": CommandPreviewSpec("a!purgeafter <message_id>", "Deleted 18 messages after the selected message", "", "delete", "Confirm purgeafter", "You are about to delete 18 messages after the selected message."),
    "lock": CommandPreviewSpec("a!lock [channel] [reason]", "Locked #general", "> Reason: Scheduled maintenance"),
    "unlock": CommandPreviewSpec("a!unlock [channel] [reason]", "Unlocked #general", "> Reason: Maintenance complete"),
    "lockall": CommandPreviewSpec(
        "a!lockall",
        "Locked 12 text channels",
        "",
        confirmation_title="Confirm lockall",
        confirmation_description="You are about to lock 12 text channels.",
    ),
    "unlockall": CommandPreviewSpec(
        "a!unlockall",
        "Unlocked 12 text channels",
        "",
        confirmation_title="Confirm unlockall",
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
    if duration is not None and "> Duration: " in description:
        description = description.replace("> Duration: 1 day", f"> Duration: {duration}")
    if count is not None and command_name in {"massban", "masskick"}:
        if total is not None and count < total:
            title = title.replace("5 members", f"{count} of {total} members")
        else:
            title = title.replace("5 members", f"{count} members")
    embed = discord.Embed(
        title=f"{emoji_markup(spec.emoji_name)} {title}",
        description=description or None,
        color=SUCCESS_COLOR,
    )
    return embed


def confirmation_embed(command_name: str, *, count: int | None = None) -> discord.Embed:
    """Build a warning embed for an action that requires confirmation."""
    spec = _get_spec(command_name)
    if spec.confirmation_title is None or spec.confirmation_description is None:
        raise ValueError(f"{command_name} does not require a confirmation preview")
    description = spec.confirmation_description
    if count is not None and command_name == "massban":
        description = f"You are about to ban {count} members."
    elif count is not None and command_name == "masskick":
        description = f"You are about to kick {count} members."
    return discord.Embed(
        title=f"{emoji_markup('warning')} {spec.confirmation_title}",
        description=description,
        color=WARNING_COLOR,
    )
