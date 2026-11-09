from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from core.utility import calculate, parse_duration_seconds
from database.repositories.community import CommunityRepository


class UtilityHelperTests(unittest.TestCase):
    def test_calculator_handles_basic_arithmetic_and_precedence(self) -> None:
        self.assertEqual(calculate("2 + 3 * 4"), 14)
        self.assertEqual(calculate("-(8 // 3)"), -2)
        self.assertEqual(calculate("2 ** -3"), 0.125)

    def test_calculator_rejects_names_calls_and_unbounded_powers(self) -> None:
        for expression in (
            "__import__('os').system('echo unsafe')",
            "open('secret')",
            "2 ** 13",
            "1 / 0",
            "True + 1",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(ValueError):
                    calculate(expression)

    def test_duration_parser_accepts_compact_and_spaced_units(self) -> None:
        self.assertEqual(parse_duration_seconds("1h 30m"), 5400)
        self.assertEqual(parse_duration_seconds("2w"), 1_209_600)
        self.assertEqual(parse_duration_seconds("45 sec"), 45)

    def test_duration_parser_rejects_invalid_or_excessive_values(self) -> None:
        for value in ("", "0m", "2x", "1mxyz", "366d"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_duration_seconds(value)


class ReminderRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "aegis.sqlite3"
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.temp_dir.cleanup()

    async def test_reminders_persist_and_can_be_claimed_or_cancelled_by_owner(self) -> None:
        due_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        reminder_id = await self.repository.create_reminder(
            user_id=20,
            message="Check the report",
            remind_at=due_at,
        )
        await self.repository.close()
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()
        self.assertEqual(len(await self.repository.list_reminders(user_id=20)), 1)
        self.assertFalse(
            await self.repository.cancel_reminder(reminder_id=reminder_id, user_id=21)
        )

        due = await self.repository.claim_due_reminders(
            now=due_at + timedelta(seconds=1)
        )
        self.assertEqual([record.reminder_id for record in due], [reminder_id])
        self.assertEqual(await self.repository.claim_due_reminders(now=due_at), [])
        self.assertTrue(await self.repository.complete_reminder(reminder_id))
        self.assertEqual(await self.repository.list_reminders(user_id=20), [])

        failed_id = await self.repository.create_reminder(
            user_id=20,
            message="Retry manually",
            remind_at=due_at,
        )
        await self.repository.claim_due_reminders(now=due_at + timedelta(seconds=1))
        self.assertTrue(await self.repository.fail_reminder(failed_id))
        self.assertEqual(
            (await self.repository.list_reminders(user_id=20))[0].status,
            "failed",
        )
        self.assertTrue(
            await self.repository.cancel_reminder(
                reminder_id=failed_id,
                user_id=20,
            )
        )


if __name__ == "__main__":
    unittest.main()
