"""Retry-safe background expiry for persisted temporary bans."""

from __future__ import annotations

import logging

import discord
from discord.ext import tasks

from database.repositories.moderation import ModerationRepository


logger = logging.getLogger(__name__)


class TempBanExpiryTask:
    def __init__(self, bot: discord.Client, repository: ModerationRepository) -> None:
        self.bot = bot
        self.repository = repository

    @tasks.loop(seconds=60)
    async def run(self) -> None:
        await self.expire_due_once()

    @run.before_loop
    async def before_run(self) -> None:
        await self.bot.wait_until_ready()

    def start(self) -> None:
        if not self.run.is_running():
            self.run.start()

    def cancel(self) -> None:
        if self.run.is_running():
            self.run.cancel()

    async def expire_due_once(self) -> None:
        cases = await self.repository.claim_expired_tempbans()
        for case in cases:
            guild = self.bot.get_guild(case.guild_id)
            if guild is None:
                await self.repository.update_case_status(case.case_id, "completed")
                continue
            try:
                await guild.unban(
                    discord.Object(id=case.target_id),
                    reason=f"Temporary ban expired for case #{case.case_id}",
                )
            except discord.NotFound:
                # An administrator may already have unbanned the member.
                await self.repository.update_case_status(case.case_id, "expired")
            except discord.HTTPException:
                logger.warning(
                    "Could not expire temporary ban case %s; it will be retried.",
                    case.case_id,
                    exc_info=True,
                )
                await self.repository.update_case_status(case.case_id, "completed")
            else:
                await self.repository.update_case_status(case.case_id, "expired")
