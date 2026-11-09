from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from cogs.giveaway import GiveawayCog
from core.giveaway_manager import GiveawayManager, GiveawayManagerError
from database.repositories.community import GiveawayRecord


def _giveaway(*, status: str = "active", winners: tuple[int, ...] = ()) -> GiveawayRecord:
    return GiveawayRecord(
        message_id=50,
        guild_id=1,
        channel_id=2,
        host_id=10,
        prize="Test prize",
        winner_count=2,
        ends_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        status=status,
        paused_seconds=None,
        winners=winners,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class GiveawayTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_rejects_prizes_that_cannot_fit_safely_in_embeds(self) -> None:
        channel = Mock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        manager = GiveawayManager(Mock(), Mock())

        with self.assertRaises(GiveawayManagerError):
            await manager.start(
                channel=channel,
                host=Mock(),
                prize="x" * 501,
                duration=timedelta(hours=1),
                winner_count=1,
            )

        channel.send.assert_not_awaited()

    async def test_required_info_command_is_registered(self) -> None:
        self.assertIsNotNone(GiveawayCog.giveaway.get_command("info"))

    async def test_pause_and_resume_preserve_remaining_time(self) -> None:
        now = datetime.now(timezone.utc)
        active = replace(_giveaway(), ends_at=(now + timedelta(minutes=2)).isoformat())
        paused = replace(active, status="paused", paused_seconds=120)
        resumed = replace(active, ends_at=(now + timedelta(minutes=2)).isoformat())
        repository = Mock()
        repository.get_giveaway = AsyncMock(side_effect=[active, paused])
        repository.update_giveaway = AsyncMock(side_effect=[paused, resumed])
        manager = GiveawayManager(SimpleNamespace(), repository)
        manager._refresh_announcement = AsyncMock()

        pause_result = await manager.pause(active.message_id)
        pause_seconds = repository.update_giveaway.await_args_list[0].kwargs[
            "paused_seconds"
        ]
        self.assertGreater(pause_seconds, 0)
        self.assertLessEqual(pause_seconds, 120)
        self.assertEqual(pause_result.status, "paused")

        resume_result = await manager.resume(active.message_id)
        resume_args = repository.update_giveaway.await_args_list[1].kwargs
        self.assertEqual(resume_args["status"], "active")
        self.assertIsNone(resume_args["paused_seconds"])
        self.assertGreater(resume_args["ends_at"], datetime.now(timezone.utc))
        self.assertEqual(resume_result.status, "active")
        self.assertEqual(manager._refresh_announcement.await_count, 2)

    async def test_delete_waits_for_other_giveaway_lifecycle_operations(self) -> None:
        repository = Mock()
        repository.get_giveaway = AsyncMock(return_value=None)
        manager = GiveawayManager(SimpleNamespace(), repository)
        await manager._lifecycle_lock.acquire()
        delete_task = asyncio.create_task(manager.delete(50))
        try:
            await asyncio.sleep(0)
            repository.get_giveaway.assert_not_awaited()
        finally:
            manager._lifecycle_lock.release()

        with self.assertRaises(GiveawayManagerError):
            await delete_task
        repository.get_giveaway.assert_awaited_once_with(50)

    async def test_end_and_reroll_store_multiple_unique_winners(self) -> None:
        channel = Mock(spec=discord.TextChannel)
        channel.send = AsyncMock()
        repository = Mock()
        active = _giveaway()
        repository.get_giveaway = AsyncMock(return_value=active)
        ended = replace(active, status="ended", winners=(20, 21))
        repository.update_giveaway = AsyncMock(return_value=ended)
        manager = GiveawayManager(
            SimpleNamespace(user=SimpleNamespace(id=99)),
            repository,
        )
        manager._participants = AsyncMock(return_value=(channel, [20, 21, 22]))
        manager._random = Mock()
        manager._random.sample = Mock(return_value=[20, 21])

        updated, winners = await manager.end(active.message_id)

        self.assertEqual(winners, (20, 21))
        self.assertEqual(updated.winners, (20, 21))
        repository.update_giveaway.assert_awaited_once_with(
            message_id=active.message_id,
            status="ended",
            winners=(20, 21),
        )

        repository.get_giveaway = AsyncMock(return_value=ended)
        rerolled = replace(ended, winners=(20, 21, 22))
        repository.update_giveaway = AsyncMock(return_value=rerolled)
        manager._participants = AsyncMock(return_value=(channel, [20, 21, 22, 23]))
        manager._random.sample = Mock(return_value=[22, 23])

        _, new_winners = await manager.end(active.message_id, reroll=True)

        self.assertEqual(new_winners, (22, 23))
        manager._random.sample.assert_called_once_with([22, 23], 2)


if __name__ == "__main__":
    unittest.main()
