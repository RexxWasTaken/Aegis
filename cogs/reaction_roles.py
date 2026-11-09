"""Reaction-role panel commands and raw reaction listeners."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from core.reaction_role_manager import (
    ReactionRoleError,
    ReactionRoleManager,
)
from database.repositories.community import CommunityRepository


logger = logging.getLogger(__name__)


def _manager(bot: commands.Bot) -> ReactionRoleManager:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The community database is not initialized.")
    return ReactionRoleManager(bot, repository)


class ReactionRolesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.manager = _manager(bot)
        self._restored = False

    @commands.hybrid_group(
        name="reactionrole",
        description="Create and manage reaction-role panels.",
        invoke_without_command=True,
    )
    @commands.guild_only()
    async def reactionrole(self, ctx: commands.Context) -> None:
        await ctx.send(
            "Use `reactionrole panel`, `add`, `remove`, `list`, or `delete`."
        )

    @reactionrole.command(name="panel", description="Create a reaction-role panel.")
    @commands.has_guild_permissions(manage_roles=True)
    @app_commands.describe(channel="Channel where the panel will be posted.")
    async def panel(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            panel = await self.manager.create_panel(
                guild=ctx.guild,
                channel=channel,
                creator_id=ctx.author.id,
            )
        except discord.HTTPException:
            await ctx.send(
                "The panel could not be posted. Check the bot's channel permissions."
            )
            return
        await ctx.send(
            f"Reaction-role panel created: message `{panel.message_id}` in {channel.mention}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @reactionrole.command(name="add", description="Map an emoji to a safe role.")
    @commands.has_guild_permissions(manage_roles=True)
    @app_commands.describe(message_id="Panel message ID.", emoji="Unicode or custom emoji.", role="Role to assign.")
    async def add(
        self,
        ctx: commands.Context,
        message_id: int,
        emoji: str,
        role: discord.Role,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            await self.manager.add_mapping(
                guild=ctx.guild,
                message_id=message_id,
                emoji_text=emoji,
                role=role,
            )
        except (ReactionRoleError, discord.HTTPException) as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            f"Mapped {emoji} to {role.mention}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @reactionrole.command(name="remove", description="Remove an emoji-role mapping.")
    @commands.has_guild_permissions(manage_roles=True)
    async def remove(
        self,
        ctx: commands.Context,
        message_id: int,
        emoji: str,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            removed = await self.manager.remove_mapping(
                guild=ctx.guild,
                message_id=message_id,
                emoji_text=emoji,
            )
        except (ReactionRoleError, discord.HTTPException) as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            "Mapping removed." if removed else "That emoji has no mapping on this panel.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @reactionrole.command(name="list", description="List this server's role panels.")
    @commands.has_guild_permissions(manage_roles=True)
    async def list_panels(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        panels = await self.manager.repository.list_reaction_role_panels(ctx.guild.id)
        if not panels:
            await ctx.send("No reaction-role panels are configured.")
            return
        lines = []
        for panel in panels[:20]:
            mappings = await self.manager.repository.list_reaction_role_mappings(
                panel.message_id
            )
            lines.append(
                f"Message `{panel.message_id}` • <#{panel.channel_id}> • "
                f"{len(mappings)} mapping(s)"
            )
        await ctx.send(
            "\n".join(lines),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @reactionrole.command(name="delete", description="Delete a reaction-role panel.")
    @commands.has_guild_permissions(manage_roles=True)
    async def delete_panel(self, ctx: commands.Context, message_id: int) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            deleted = await self.manager.delete_panel(
                guild=ctx.guild,
                message_id=message_id,
            )
        except (ReactionRoleError, discord.HTTPException) as exc:
            await ctx.send(str(exc), allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(
            "Reaction-role panel deleted."
            if deleted
            else "That reaction-role panel was not found.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._restored:
            return
        self._restored = True
        await self.manager.restore_panels()

    @commands.Cog.listener()
    async def on_raw_reaction_add(
        self,
        payload: discord.RawReactionActionEvent,
    ) -> None:
        try:
            await self.manager.handle_reaction_add(payload)
        except (ValueError, discord.HTTPException):
            logger.exception("Reaction-role add event failed.")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(
        self,
        payload: discord.RawReactionActionEvent,
    ) -> None:
        try:
            await self.manager.handle_reaction_remove(payload)
        except (ValueError, discord.HTTPException):
            logger.exception("Reaction-role remove event failed.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRolesCog(bot))
