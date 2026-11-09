"""AEGIS Discord bot wiring for the moderation module."""

from __future__ import annotations

import os
import logging
from pathlib import Path

import discord
from discord.ext import commands

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
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.reactions = True
        intents.voice_states = True
        if hasattr(intents, "moderation"):
            intents.moderation = True
        super().__init__(command_prefix="a!", intents=intents, help_command=None)
        self.database_path = str(
            database_path or os.environ.get("AEGIS_DB_PATH", "data/moderation.sqlite3")
        )
        self.moderation_repository: ModerationRepository | None = None
        self.moderation_service: ModerationService | None = None
        self.tempban_expiry_task: TempBanExpiryTask | None = None
        self.community_repository: CommunityRepository | None = None
        self.music_manager: MusicManager | None = None
        self._application_commands_synced = False

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
