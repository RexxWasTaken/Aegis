from __future__ import annotations

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
