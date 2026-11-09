"""Persistent welcome and goodbye message delivery."""

from __future__ import annotations

import logging
import re

import discord

from database.repositories.community import CommunityRepository


logger = logging.getLogger(__name__)
_VARIABLE = re.compile(r"\{(user|username|server|member_count)\}")


class WelcomeManager:
    def __init__(self, bot: discord.Client, repository: CommunityRepository) -> None:
        self.bot = bot
        self.repository = repository

    @staticmethod
    def render_message(template: str, member: discord.Member) -> str:
        guild = member.guild
        values = {
            "user": member.mention,
            "username": member.name,
            "server": guild.name,
            "member_count": str(guild.member_count or len(guild.members)),
        }
        return _VARIABLE.sub(lambda match: str(values[match.group(1)]), template)

    async def send_for_member(self, member: discord.Member, kind: str) -> bool:
        if kind not in {"welcome", "goodbye"}:
            raise ValueError("Message type must be welcome or goodbye.")
        config = await self.repository.get_welcome_config(member.guild.id)
        if config is None or not getattr(config, f"{kind}_enabled"):
            return False
        channel_id = getattr(config, f"{kind}_channel_id")
        template = getattr(config, f"{kind}_message")
        if channel_id is None or template is None:
            return False
        channel = member.guild.get_channel(channel_id)
        if channel is None:
            logger.warning(
                "Configured %s channel %s is unavailable in guild %s.",
                kind,
                channel_id,
                member.guild.id,
            )
            return False
        await channel.send(
            self.render_message(template, member),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True
