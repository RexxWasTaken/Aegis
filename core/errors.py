"""Central command error handling for moderation commands."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from core.permissions import ModerationPermissionError, ModerationTargetError
from embeds.moderation import COMMAND_SPECS
from embeds.moderation_errors import (
    missing_permissions_embed,
    operation_error_embed,
    wrong_usage_embed,
)
from services.moderation_service import ModerationServiceError


logger = logging.getLogger(__name__)


async def handle_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.CommandNotFound):
        return

    original = getattr(error, "original", error)
    command_name = ctx.command.name if ctx.command is not None else ""
    if isinstance(original, (commands.MemberNotFound, commands.UserNotFound)):
        embed = operation_error_embed(
            "The specified user could not be resolved.", guild=ctx.guild
        )
    elif isinstance(original, (commands.MissingRequiredArgument, commands.BadArgument)):
        embed = (
            wrong_usage_embed(command_name, guild=ctx.guild)
            if command_name
            else operation_error_embed("The command arguments are invalid.", guild=ctx.guild)
        )
    elif isinstance(
        original,
        (
            commands.MissingPermissions,
            commands.BotMissingPermissions,
            ModerationPermissionError,
            discord.Forbidden,
        ),
    ):
        embed = (
            missing_permissions_embed(command_name, guild=ctx.guild)
            if command_name in COMMAND_SPECS
            else operation_error_embed(
                "The required permissions are missing.", guild=ctx.guild
            )
        )
    elif isinstance(original, (ModerationTargetError, ModerationServiceError)):
        embed = operation_error_embed(str(original), guild=ctx.guild)
    elif isinstance(original, discord.HTTPException):
        logger.warning("Discord rejected moderation command %s (%s).", command_name, original.status)
        embed = operation_error_embed(
            "Discord could not complete this moderation action.", guild=ctx.guild
        )
    elif isinstance(original, commands.NoPrivateMessage):
        embed = operation_error_embed(
            "This moderation command can only be used in a server.", guild=ctx.guild
        )
    else:
        logger.error("Unhandled command error for %s: %r", command_name, original)
        embed = operation_error_embed(
            "The command could not be completed.", guild=ctx.guild
        )

    try:
        await ctx.reply(
            embed=embed,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException:
        logger.warning("Could not send an error response for command %s.", command_name)
