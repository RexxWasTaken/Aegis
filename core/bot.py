"""AEGIS Discord bot wiring for the moderation module."""

from __future__ import annotations

import os
import logging
import re
from pathlib import Path

import discord
from discord.ext import commands

from core.configuration import get_default_prefix, get_owner_id
from core.errors import handle_command_error
from core.loader import load_extensions
from core.music_manager import MusicManager
from database.repositories.community import CommunityRepository
from database.repositories.moderation import ModerationRepository
from services.moderation_service import ModerationService
from tasks.tempban_expiry import TempBanExpiryTask


logger = logging.getLogger(__name__)


class AegisBot(commands.Bot):
    def __init__(self, *, database_path: str | Path | None = None) -> None:
        self.default_prefix = get_default_prefix()
        configured_owner_id = get_owner_id()
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        intents.voice_states = True
        if hasattr(intents, "moderation"):
            intents.moderation = True
        super().__init__(
            command_prefix=self.get_prefix,
            owner_id=configured_owner_id,
            intents=intents,
            help_command=None,
            strip_after_prefix=True,
        )
        self.database_path = str(
            database_path or os.environ.get("AEGIS_DB_PATH", "data/moderation.sqlite3")
        )
        self.moderation_repository: ModerationRepository | None = None
        self.moderation_service: ModerationService | None = None
        self.tempban_expiry_task: TempBanExpiryTask | None = None
        self.community_repository: CommunityRepository | None = None
        self.music_manager: MusicManager | None = None
        self._application_commands_synced = False

    async def is_owner(self, user: discord.User | discord.Member) -> bool:
        """Never fall back to application ownership when OWNER_ID is unset."""
        return self.owner_id is not None and user.id == self.owner_id

    async def get_guild_prefix(self, guild_id: int | None) -> str:
        """Return a saved server prefix or the configured default for DMs/new servers."""
        if guild_id is None or self.community_repository is None:
            return self.default_prefix
        return await self.community_repository.get_guild_prefix(
            guild_id,
            default_prefix=self.default_prefix,
        )

    async def get_prefix(self, message: discord.Message) -> list[str]:
        """Use the server prefix and mentions; empty-prefix parsing is per-user only."""
        guild_id = message.guild.id if message.guild is not None else None
        prefix = await self.get_guild_prefix(guild_id)
        prefixes = list(commands.when_mentioned_or(prefix)(self, message))
        repository = self.community_repository
        if repository is not None and await repository.has_no_prefix_user(message.author.id):
            prefixes.append("")
        return prefixes

    async def _reply_to_mention_only(self, message: discord.Message) -> bool:
        """Reply only when this message consists of bot mentions and punctuation."""
        bot_user = self.user
        if bot_user is None or not any(user.id == bot_user.id for user in message.mentions):
            return False
        remainder = re.sub(rf"<@!?{bot_user.id}>", "", message.content)
        if remainder.strip(" \t\r\n.,!?"):
            return False
        guild_id = message.guild.id if message.guild is not None else None
        prefix = await self.get_guild_prefix(guild_id)
        try:
            await message.channel.send(
                f"Hey! My prefix here is `{prefix}`.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.debug("Could not send the mention-prefix response.")
        return True

    async def on_message(self, message: discord.Message) -> None:
        """Handle mention-only prompts and then process ordinary bot commands."""
        if message.author.bot or message.webhook_id is not None:
            return
        if await self._reply_to_mention_only(message):
            return
        await self.process_commands(message)

    async def setup_hook(self) -> None:
        repository = ModerationRepository(self.database_path)
        await repository.initialize()
        self.moderation_repository = repository
        self.moderation_service = ModerationService(repository)
        community_repository = CommunityRepository(self.database_path)
        await community_repository.initialize()
        self.community_repository = community_repository
        self.music_manager = MusicManager(self)
        await self.music_manager.connect(attempts=1, timeout=5.0)
        await load_extensions(self)
        self.tempban_expiry_task = TempBanExpiryTask(self, repository)
        self.tempban_expiry_task.start()

    async def on_ready(self) -> None:
        if self.tree.get_commands() and not self._application_commands_synced:
            try:
                await self.tree.sync()
            except discord.HTTPException:
                logger.exception("Could not synchronize AEGIS slash commands.")
            else:
                self._application_commands_synced = True

    async def on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        await handle_command_error(ctx, error)

    async def close(self) -> None:
        giveaway_cog = self.get_cog("GiveawayCog")
        if giveaway_cog is not None:
            giveaway_cog.expire_due_giveaways.cancel()
        music_events = self.get_cog("MusicPlayerEvents")
        if music_events is not None:
            music_events.refresh_music_panels.cancel()
        if self.music_manager is not None:
            await self.music_manager.close()
            self.music_manager = None
        if self.tempban_expiry_task is not None:
            self.tempban_expiry_task.cancel()
            self.tempban_expiry_task = None
        if self.community_repository is not None:
            await self.community_repository.close()
            self.community_repository = None
        if self.moderation_repository is not None:
            await self.moderation_repository.close()
            self.moderation_repository = None
        await super().close()
