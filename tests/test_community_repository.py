from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database.repositories.community import CommunityRepository


class CommunityRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "aegis.sqlite3"
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.temp_dir.cleanup()

    async def test_ticket_configuration_state_and_event_log_persist(self) -> None:
        config = await self.repository.set_ticket_config(
            guild_id=10,
            staff_role_id=20,
            category_id=30,
            log_channel_id=40,
        )
        self.assertEqual(config.staff_role_id, 20)

        ticket = await self.repository.create_ticket(
            guild_id=10,
            channel_id=100,
            creator_id=200,
            category="General Support",
        )
        self.assertEqual(ticket.status, "open")
        self.assertEqual(
            (await self.repository.get_open_ticket(guild_id=10, creator_id=200)).ticket_id,
            ticket.ticket_id,
        )
        with self.assertRaises(ValueError):
            await self.repository.create_ticket(
                guild_id=10,
                channel_id=101,
                creator_id=200,
                category="Other",
            )
        await self.repository.claim_ticket(channel_id=100, staff_id=300)
        await self.repository.log_ticket_event(
            ticket_id=ticket.ticket_id,
            guild_id=10,
            actor_id=300,
            event="Claimed",
            details="Claimed for testing.",
        )
        await self.repository.set_ticket_status(
            channel_id=100,
            status="closed",
            closed_at=datetime.now(timezone.utc).isoformat(),
        )

        await self.repository.close()
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()
        saved_config = await self.repository.get_ticket_config(10)
        saved_ticket = await self.repository.get_ticket(100)
        self.assertEqual(saved_config.staff_role_id, 20)
        self.assertEqual(saved_ticket.status, "closed")
        self.assertIsNone(
            await self.repository.get_open_ticket(guild_id=10, creator_id=200)
        )
        cursor = await self.repository._connection().execute(
            "SELECT event FROM ticket_events WHERE ticket_id = ?", (ticket.ticket_id,)
        )
        self.assertEqual((await cursor.fetchone())["event"], "Claimed")

    async def test_giveaway_lifecycle_is_durable_and_due_lookup_is_status_scoped(self) -> None:
        due_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        giveaway = await self.repository.create_giveaway(
            message_id=500,
            guild_id=10,
            channel_id=11,
            host_id=12,
            prize="Test prize",
            winner_count=2,
            ends_at=due_time,
        )
        self.assertEqual(giveaway.status, "active")
        self.assertEqual([item.message_id for item in await self.repository.due_giveaways()], [500])

        paused = await self.repository.update_giveaway(
            message_id=500,
            status="paused",
            paused_seconds=120,
        )
        self.assertEqual(paused.paused_seconds, 120)
        self.assertEqual(await self.repository.due_giveaways(), [])

        resumed = await self.repository.update_giveaway(
            message_id=500,
            status="active",
            ends_at=datetime.now(timezone.utc) + timedelta(seconds=120),
            paused_seconds=None,
        )
        ended = await self.repository.update_giveaway(
            message_id=500,
            status="ended",
            winners=(21, 22),
        )
        self.assertEqual(resumed.status, "active")
        self.assertEqual(ended.winners, (21, 22))
        self.assertEqual(await self.repository.list_giveaways(guild_id=10), [])

        await self.repository.close()
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()
        stored = await self.repository.get_giveaway(500)
        self.assertEqual(stored.status, "ended")
        self.assertEqual(stored.winners, (21, 22))
        self.assertTrue(await self.repository.delete_giveaway(500))
        self.assertIsNone(await self.repository.get_giveaway(500))


if __name__ == "__main__":
    unittest.main()
