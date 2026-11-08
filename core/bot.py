"""AEGIS Discord bot wiring for the moderation module."""

from __future__ import annotations

import os
from pathlib import Path

import discord
from discord.ext import commands

from core.errors import handle_command_error
from core.loader import load_extensions
from database.repositories.moderation import ModerationRepository
from services.moderation_service import ModerationService
from tasks.tempban_expiry import TempBanExpiryTask


class AegisBot(commands.Bot):
    def __init__(self, *, database_path: str | Path | None = None) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="a!", intents=intents, help_command=None)
        self.database_path = str(
            database_path or os.environ.get("AEGIS_DB_PATH", "data/moderation.sqlite3")
        )
        self.moderation_repository: ModerationRepository | None = None
        self.moderation_service: ModerationService | None = None
        self.tempban_expiry_task: TempBanExpiryTask | None = None

    async def setup_hook(self) -> None:
        repository = ModerationRepository(self.database_path)
        await repository.initialize()
        self.moderation_repository = repository
        self.moderation_service = ModerationService(repository)
        await load_extensions(self)
        self.tempban_expiry_task = TempBanExpiryTask(self, repository)
        self.tempban_expiry_task.start()

    async def on_command_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ) -> None:
        await handle_command_error(ctx, error)

    async def close(self) -> None:
        if self.tempban_expiry_task is not None:
            self.tempban_expiry_task.cancel()
            self.tempban_expiry_task = None
        if self.moderation_repository is not None:
            await self.moderation_repository.close()
            self.moderation_repository = None
        await super().close()
