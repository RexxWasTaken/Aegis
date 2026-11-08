from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import aiosqlite

from database.repositories.moderation import ModerationRepository


class ModerationDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "moderation.sqlite3"
        self.repository = ModerationRepository(self.path)

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.temp_dir.cleanup()

    async def test_case_lifecycle_uses_parameterized_persistent_records(self) -> None:
        await self.repository.initialize()
        case = await self.repository.create_case(
            guild_id=1,
            target_id=2,
            moderator_id=3,
            action_type="ban",
            reason="test reason'; DROP TABLE moderation_cases; --",
        )
        self.assertEqual(case.status, "pending")
        self.assertEqual(case.reason, "test reason'; DROP TABLE moderation_cases; --")
        await self.repository.update_case_status(case.case_id, "completed")
        saved = await self.repository.get_case(case.case_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.status, "completed")
        self.assertEqual(saved.action_type, "ban")
        self.assertEqual(saved.target_id, 2)

    async def test_migration_preserves_existing_rows_and_adds_status(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                CREATE TABLE moderation_cases (
                    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            await db.execute(
                """
                INSERT INTO moderation_cases
                    (guild_id, target_id, moderator_id, action_type, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (1, 2, 3, "ban", "old case", "2026-01-01T00:00:00+00:00"),
            )
            await db.commit()
        await self.repository.initialize()
        saved = await self.repository.get_case(1)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.reason, "old case")
        self.assertEqual(saved.status, "completed")

    async def test_invalid_status_is_rejected(self) -> None:
        await self.repository.initialize()
        case = await self.repository.create_case(
            guild_id=1,
            target_id=2,
            moderator_id=3,
            action_type="unban",
            reason="reviewed",
        )
        with self.assertRaises(ValueError):
            await self.repository.update_case_status(case.case_id, "deleted")

    async def test_warnings_persist_and_are_scoped_by_guild_target_and_id(self) -> None:
        await self.repository.initialize()
        first = await self.repository.create_warning(
            guild_id=1, target_id=2, moderator_id=3, reason="first"
        )
        second = await self.repository.create_warning(
            guild_id=1, target_id=2, moderator_id=4, reason="second"
        )
        other_guild = await self.repository.create_warning(
            guild_id=2, target_id=2, moderator_id=5, reason="different guild"
        )
        other_target = await self.repository.create_warning(
            guild_id=1, target_id=6, moderator_id=7, reason="different target"
        )
        self.assertEqual(first.target_id, 2)
        self.assertEqual(first.moderator_id, 3)
        self.assertTrue(first.created_at)

        await self.repository.close()
        self.repository = ModerationRepository(self.path)
        await self.repository.initialize()
        warnings = await self.repository.list_warnings(guild_id=1, target_id=2)
        self.assertEqual([item.warning_id for item in warnings], [second.warning_id, first.warning_id])
        self.assertEqual(warnings[0].reason, "second")

        self.assertIsNone(
            await self.repository.delete_warning(
                guild_id=2, target_id=2, warning_id=first.warning_id
            )
        )
        removed = await self.repository.delete_warning(
            guild_id=1, target_id=2, warning_id=second.warning_id
        )
        self.assertEqual(removed, second)
        self.assertEqual(
            await self.repository.clear_warnings(guild_id=1, target_id=2), 1
        )
        self.assertEqual(
            await self.repository.list_warnings(guild_id=1, target_id=2), []
        )
        self.assertEqual(
            [item.warning_id for item in await self.repository.list_warnings(
                guild_id=2, target_id=2
            )],
            [other_guild.warning_id],
        )
        self.assertEqual(
            [item.warning_id for item in await self.repository.list_warnings(
                guild_id=1, target_id=6
            )],
            [other_target.warning_id],
        )

    async def test_expired_tempban_is_claimed_once_for_expiry(self) -> None:
        from datetime import datetime, timezone

        await self.repository.initialize()
        case = await self.repository.create_case(
            guild_id=1,
            target_id=2,
            moderator_id=3,
            action_type="tempban",
            reason="temporary",
            expires_at="2026-01-01T00:00:00+00:00",
        )
        await self.repository.update_case_status(case.case_id, "completed")
        now = datetime(2026, 1, 2, tzinfo=timezone.utc)
        due = await self.repository.claim_expired_tempbans(now)
        self.assertEqual([item.case_id for item in due], [case.case_id])
        self.assertEqual(due[0].status, "expiry_pending")
        self.assertEqual(await self.repository.claim_expired_tempbans(now), [])


if __name__ == "__main__":
    unittest.main()
