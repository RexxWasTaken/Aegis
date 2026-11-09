"""Safe, database-backed reaction-role panels."""

from __future__ import annotations

import logging
import unicodedata

import discord

from database.repositories.community import (
    CommunityRepository,
    ReactionRoleMapping,
    ReactionRolePanel,
)
from embeds.reaction_roles import reaction_role_panel_embed


logger = logging.getLogger(__name__)
MAX_MAPPINGS_PER_PANEL = 20
_DANGEROUS_PERMISSIONS = (
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "manage_messages",
    "manage_threads",
    "manage_expressions",
    "manage_events",
    "ban_members",
    "kick_members",
    "moderate_members",
    "mention_everyone",
)


class ReactionRoleError(ValueError):
    """A panel or role assignment is invalid or unsafe."""


def normalize_emoji(value: str | discord.PartialEmoji) -> str:
    emoji = value if isinstance(value, discord.PartialEmoji) else discord.PartialEmoji.from_str(
        value.strip()
    )
    if emoji.id is not None:
        return f"custom:{emoji.id}"
    rendered = unicodedata.normalize("NFC", str(emoji)).strip()
    if not rendered or any(character.isspace() for character in rendered):
        raise ReactionRoleError("Provide one Unicode emoji or a custom server emoji.")
    return f"unicode:{rendered}"


def _emoji_from_text(value: str) -> str | discord.PartialEmoji:
    parsed = discord.PartialEmoji.from_str(value.strip())
    return parsed if parsed.id is not None else value.strip()


class ReactionRoleManager:
    def __init__(
        self,
        bot: discord.Client,
        repository: CommunityRepository,
    ) -> None:
        self.bot = bot
        self.repository = repository

    @staticmethod
    def role_is_safe(guild: discord.Guild, role: discord.Role) -> bool:
        if role.id == guild.id or role.managed:
            return False
        default_check = getattr(role, "is_default", None)
        if callable(default_check) and default_check():
            return False
        assignable = getattr(role, "is_assignable", False)
        if callable(assignable):
            assignable = assignable()
        bot_member = guild.me
        if not assignable or bot_member is None:
            return False
        if role.position >= bot_member.top_role.position:
            return False
        permissions = role.permissions
        return not any(bool(getattr(permissions, name, False)) for name in _DANGEROUS_PERMISSIONS)

    async def create_panel(
        self,
        *,
        guild: discord.Guild,
        channel: discord.TextChannel,
        creator_id: int,
    ) -> ReactionRolePanel:
        message = await channel.send(
            embed=reaction_role_panel_embed(()),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        try:
            return await self.repository.create_reaction_role_panel(
                message_id=message.id,
                guild_id=guild.id,
                channel_id=channel.id,
                created_by=creator_id,
            )
        except Exception:
            try:
                await message.delete()
            except discord.HTTPException:
                logger.exception("Could not remove an unregistered reaction-role panel.")
            raise

    async def add_mapping(
        self,
        *,
        guild: discord.Guild,
        message_id: int,
        emoji_text: str,
        role: discord.Role,
    ) -> ReactionRoleMapping:
        panel = await self.repository.get_reaction_role_panel(message_id)
        if panel is None or panel.guild_id != guild.id:
            raise ReactionRoleError("That message is not a panel in this server.")
        if not self.role_is_safe(guild, role):
            raise ReactionRoleError(
                "That role cannot be self-assigned: it may be managed, too high, "
                "or grant powerful permissions."
            )
        mappings = await self.repository.list_reaction_role_mappings(message_id)
        if len(mappings) >= MAX_MAPPINGS_PER_PANEL:
            raise ReactionRoleError("A panel can have at most 20 role mappings.")
        emoji = _emoji_from_text(emoji_text)
        emoji_key = normalize_emoji(emoji)
        mapping = await self.repository.add_reaction_role_mapping(
            message_id=message_id,
            guild_id=guild.id,
            emoji_key=emoji_key,
            emoji=str(emoji),
            role_id=role.id,
        )
        try:
            message = await self._fetch_message(guild, panel)
            await message.add_reaction(emoji)
            updated = await self.repository.list_reaction_role_mappings(message_id)
            await message.edit(
                embed=reaction_role_panel_embed(updated),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception as exc:
            await self.repository.remove_reaction_role_mapping(
                message_id=message_id,
                emoji_key=emoji_key,
            )
            raise ReactionRoleError(
                "The reaction could not be added. Check the bot's channel permissions "
                "and emoji access."
            ) from exc
        return mapping

    async def _fetch_message(
        self,
        guild: discord.Guild,
        panel: ReactionRolePanel,
    ) -> discord.Message:
        channel = guild.get_channel(panel.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(panel.channel_id)
            except discord.HTTPException as exc:
                raise ReactionRoleError("The panel channel is unavailable.") from exc
        if getattr(channel, "guild", None) is None or channel.guild.id != guild.id:
            raise ReactionRoleError("The panel channel is not in this server.")
        try:
            return await channel.fetch_message(panel.message_id)
        except discord.HTTPException as exc:
            raise ReactionRoleError("The panel message could not be found.") from exc

    async def _remove_reactors(
        self,
        *,
        guild: discord.Guild,
        reaction: discord.Reaction | None,
        role: discord.Role | None,
    ) -> None:
        if reaction is None or role is None:
            return
        try:
            async for user in reaction.users(limit=1000):
                if user.bot:
                    continue
                member = guild.get_member(user.id)
                if member is None:
                    try:
                        member = await guild.fetch_member(user.id)
                    except discord.HTTPException:
                        continue
                if role in member.roles:
                    try:
                        await member.remove_roles(
                            role,
                            reason="Reaction-role mapping removed",
                        )
                    except discord.HTTPException:
                        logger.warning(
                            "Could not remove a reaction role from member %s.", user.id
                        )
        except discord.HTTPException:
            logger.warning("Could not inspect all users on a removed reaction.")

    async def remove_mapping(
        self,
        *,
        guild: discord.Guild,
        message_id: int,
        emoji_text: str,
    ) -> bool:
        panel = await self.repository.get_reaction_role_panel(message_id)
        if panel is None or panel.guild_id != guild.id:
            raise ReactionRoleError("That message is not a panel in this server.")
        emoji_key = normalize_emoji(emoji_text)
        mapping = await self.repository.get_reaction_role_mapping(
            message_id=message_id,
            emoji_key=emoji_key,
        )
        if mapping is None:
            return False
        message = await self._fetch_message(guild, panel)
        reaction = next(
            (
                item
                for item in message.reactions
                if normalize_emoji(item.emoji) == emoji_key
            ),
            None,
        )
        await self._remove_reactors(
            guild=guild,
            reaction=reaction,
            role=guild.get_role(mapping.role_id),
        )
        await self.repository.remove_reaction_role_mapping(
            message_id=message_id,
            emoji_key=emoji_key,
        )
        if reaction is not None:
            try:
                await message.clear_reaction(reaction.emoji)
            except discord.HTTPException:
                logger.warning("Could not clear a removed reaction-role emoji.")
        mappings = await self.repository.list_reaction_role_mappings(message_id)
        await message.edit(
            embed=reaction_role_panel_embed(mappings),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

    async def delete_panel(
        self,
        *,
        guild: discord.Guild,
        message_id: int,
    ) -> bool:
        panel = await self.repository.get_reaction_role_panel(message_id)
        if panel is None or panel.guild_id != guild.id:
            raise ReactionRoleError("That message is not a panel in this server.")
        message = await self._fetch_message(guild, panel)
        mappings = await self.repository.list_reaction_role_mappings(message_id)
        for mapping in mappings:
            reaction = next(
                (
                    item
                    for item in message.reactions
                    if normalize_emoji(item.emoji) == mapping.emoji_key
                ),
                None,
            )
            await self._remove_reactors(
                guild=guild,
                reaction=reaction,
                role=guild.get_role(mapping.role_id),
            )
        await message.delete()
        return await self.repository.delete_reaction_role_panel(message_id)

    async def handle_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.user_id == getattr(self.bot.user, "id", None):
            return
        mapping = await self.repository.get_reaction_role_mapping(
            message_id=payload.message_id,
            emoji_key=normalize_emoji(payload.emoji),
        )
        if mapping is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(mapping.role_id)
        if role is None or not self.role_is_safe(guild, role):
            return
        member = payload.member or guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.HTTPException:
                return
        if member.bot or role in member.roles:
            return
        try:
            await member.add_roles(role, reason="Reaction-role panel selection")
        except discord.HTTPException:
            logger.warning("Could not assign a reaction role to member %s.", member.id)

    async def handle_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.user_id == getattr(self.bot.user, "id", None):
            return
        mapping = await self.repository.get_reaction_role_mapping(
            message_id=payload.message_id,
            emoji_key=normalize_emoji(payload.emoji),
        )
        if mapping is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        role = guild.get_role(mapping.role_id)
        member = guild.get_member(payload.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(payload.user_id)
            except discord.HTTPException:
                return
        if role is None or role not in member.roles:
            return
        try:
            await member.remove_roles(role, reason="Reaction-role panel selection removed")
        except discord.HTTPException:
            logger.warning("Could not remove a reaction role from member %s.", member.id)

    async def restore_panels(self) -> None:
        for panel in await self.repository.list_reaction_role_panels():
            guild = self.bot.get_guild(panel.guild_id)
            if guild is None:
                continue
            try:
                message = await self._fetch_message(guild, panel)
            except ReactionRoleError:
                continue
            mappings = await self.repository.list_reaction_role_mappings(panel.message_id)
            try:
                await message.edit(
                    embed=reaction_role_panel_embed(mappings),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                existing = {normalize_emoji(item.emoji) for item in message.reactions}
                for mapping in mappings:
                    if mapping.emoji_key not in existing:
                        await message.add_reaction(_emoji_from_text(mapping.emoji))
            except discord.HTTPException:
                logger.warning(
                    "Could not restore reaction-role panel %s.", panel.message_id
                )
