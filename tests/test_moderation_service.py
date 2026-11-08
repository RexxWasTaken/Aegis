from __future__ import annotations

import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from database.repositories.moderation import ModerationCase
from services.moderation_service import (
    AuditLogError,
    ModerationService,
    ModerationServiceError,
    normalize_reason,
)
from tasks.tempban_expiry import TempBanExpiryTask
from utils.duration import format_duration, parse_duration


def case_record(action: str = "ban") -> ModerationCase:
    return ModerationCase(
        case_id=7,
        guild_id=1,
        target_id=30,
        moderator_id=10,
        action_type=action,
        reason="Rule violation",
        created_at="2026-01-01T00:00:00+00:00",
        expires_at=None,
        status="pending",
    )


class ModerationServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.guild = SimpleNamespace(id=1, owner_id=99, unban=AsyncMock())
        self.moderator = SimpleNamespace(
            id=10,
            guild=self.guild,
            bot=False,
            top_role=SimpleNamespace(position=5),
            guild_permissions=SimpleNamespace(ban_members=True),
        )
        self.bot_member = SimpleNamespace(
            id=20,
            guild=self.guild,
            top_role=SimpleNamespace(position=10),
            guild_permissions=SimpleNamespace(ban_members=True),
        )
        self.target = SimpleNamespace(
            id=30,
            guild=self.guild,
            top_role=SimpleNamespace(position=2),
            ban=AsyncMock(),
            kick=AsyncMock(),
        )
        self.repository = SimpleNamespace(
            create_case=AsyncMock(return_value=case_record()),
            update_case_status=AsyncMock(),
        )
        self.service = ModerationService(self.repository)

    async def test_ban_records_case_and_calls_discord_without_deleting_messages(self) -> None:
        result = await self.service.ban_member(
            guild=self.guild,
            target=self.target,
            moderator=self.moderator,
            bot_member=self.bot_member,
            reason="Rule violation",
        )
        self.assertEqual(result.case_id, 7)
        self.repository.create_case.assert_awaited_once_with(
            guild_id=1,
            target_id=30,
            moderator_id=10,
            action_type="ban",
            reason="Rule violation",
        )
        self.target.ban.assert_awaited_once_with(
            reason="Case #7: Rule violation",
            delete_message_seconds=0,
        )
        self.repository.update_case_status.assert_awaited_once_with(7, "completed")

    async def test_unban_records_case_and_calls_discord(self) -> None:
        self.repository.create_case.return_value = case_record("unban")
        target_user = SimpleNamespace(id=55)
        await self.service.unban_user(
            guild=self.guild,
            target=target_user,
            moderator=self.moderator,
            bot_member=self.bot_member,
            reason="Appeal accepted",
        )
        self.repository.create_case.assert_awaited_once_with(
            guild_id=1,
            target_id=55,
            moderator_id=10,
            action_type="unban",
            reason="Appeal accepted",
        )
        self.guild.unban.assert_awaited_once()
        self.assertEqual(self.guild.unban.await_args.args[0].id, 55)
        self.repository.update_case_status.assert_awaited_once_with(7, "completed")

    async def test_failed_discord_action_marks_case_failed(self) -> None:
        self.target.ban.side_effect = RuntimeError("discord request failed")
        with self.assertRaisesRegex(RuntimeError, "discord request failed"):
            await self.service.ban_member(
                guild=self.guild,
                target=self.target,
                moderator=self.moderator,
                bot_member=self.bot_member,
                reason="Rule violation",
            )
        self.repository.update_case_status.assert_awaited_once_with(7, "failed")

    async def test_case_finalize_failure_does_not_claim_action_failed(self) -> None:
        self.repository.update_case_status.side_effect = RuntimeError("database unavailable")
        with self.assertRaises(AuditLogError) as raised:
            await self.service.ban_member(
                guild=self.guild,
                target=self.target,
                moderator=self.moderator,
                bot_member=self.bot_member,
                reason="Rule violation",
            )
        self.assertTrue(raised.exception.action_applied)
        self.target.ban.assert_awaited_once()

    async def test_reason_length_is_bounded(self) -> None:
        self.assertEqual(normalize_reason("  reviewed  "), "reviewed")
        with self.assertRaises(ValueError):
            normalize_reason("x" * 451)

    async def test_softban_unbans_after_cleanup_ban(self) -> None:
        self.repository.create_case.return_value = case_record("softban")
        await self.service.softban_member(
            guild=self.guild,
            target=self.target,
            moderator=self.moderator,
            bot_member=self.bot_member,
            reason="Cleanup",
        )
        self.target.ban.assert_awaited_once_with(
            reason="Case #7: Cleanup",
            delete_message_seconds=604800,
        )
        self.guild.unban.assert_awaited_once()
        self.repository.update_case_status.assert_awaited_once_with(7, "completed")

    async def test_softban_marks_partial_if_automatic_unban_fails(self) -> None:
        self.repository.create_case.return_value = case_record("softban")
        self.guild.unban.side_effect = RuntimeError("unban failed")
        with self.assertRaisesRegex(ModerationServiceError, "automatic unban failed"):
            await self.service.softban_member(
                guild=self.guild,
                target=self.target,
                moderator=self.moderator,
                bot_member=self.bot_member,
                reason="Cleanup",
            )
        self.repository.update_case_status.assert_awaited_once_with(7, "partial")

    async def test_tempban_persists_expiry_and_bans_without_deleting_history(self) -> None:
        self.repository.create_case.return_value = case_record("tempban")
        await self.service.tempban_member(
            guild=self.guild,
            target=self.target,
            moderator=self.moderator,
            bot_member=self.bot_member,
            duration=timedelta(hours=2),
            reason="Repeated spam",
        )
        args = self.repository.create_case.await_args.kwargs
        self.assertEqual(args["action_type"], "tempban")
        self.assertIsNotNone(args["expires_at"])
        self.target.ban.assert_awaited_once_with(
            reason="Case #7: Repeated spam",
            delete_message_seconds=0,
        )

    async def test_duration_parser_is_bounded_and_human_readable(self) -> None:
        self.assertEqual(parse_duration("10m"), timedelta(minutes=10))
        self.assertEqual(format_duration(parse_duration("2h")), "2 hours")
        with self.assertRaises(ValueError):
            parse_duration("0m")
        with self.assertRaises(ValueError):
            parse_duration("400d")

    async def test_tempban_expiry_worker_unbans_and_marks_case_expired(self) -> None:
        expired_case = case_record("tempban")
        expired_case = ModerationCase(
            **{**expired_case.__dict__, "status": "expiry_pending"}
        )
        repo = SimpleNamespace(
            claim_expired_tempbans=AsyncMock(return_value=[expired_case]),
            update_case_status=AsyncMock(),
        )
        guild = SimpleNamespace(id=1, unban=AsyncMock())
        bot = SimpleNamespace(get_guild=lambda guild_id: guild)
        worker = TempBanExpiryTask(bot, repo)
        await worker.expire_due_once()
        guild.unban.assert_awaited_once()
        repo.update_case_status.assert_awaited_once_with(7, "expired")

    async def test_kick_records_case_and_calls_discord(self) -> None:
        self.moderator.guild_permissions.kick_members = True
        self.bot_member.guild_permissions.kick_members = True
        await self.service.kick_member(
            guild=self.guild,
            target=self.target,
            moderator=self.moderator,
            bot_member=self.bot_member,
            reason="Rule violation",
        )
        self.repository.create_case.assert_awaited_once_with(
            guild_id=1,
            target_id=30,
            moderator_id=10,
            action_type="kick",
            reason="Rule violation",
        )
        self.target.kick.assert_awaited_once_with(reason="Case #7: Rule violation")
        self.repository.update_case_status.assert_awaited_once_with(7, "completed")

    async def test_massban_returns_actual_partial_results(self) -> None:
        self.repository.create_case.side_effect = [
            case_record("massban"),
            ModerationCase(
                case_id=8,
                guild_id=1,
                target_id=31,
                moderator_id=10,
                action_type="massban",
                reason="Coordinated raid",
                created_at="2026-01-01T00:00:00+00:00",
                expires_at=None,
                status="pending",
            ),
        ]
        second = SimpleNamespace(
            id=31,
            guild=self.guild,
            top_role=SimpleNamespace(position=1),
            ban=AsyncMock(side_effect=RuntimeError("discord rejected this target")),
        )
        result = await self.service.massban_members(
            guild=self.guild,
            targets=[self.target, second],
            moderator=self.moderator,
            bot_member=self.bot_member,
            reason="Coordinated raid",
        )
        self.assertEqual(result.attempted, 2)
        self.assertEqual(result.completed_target_ids, (30,))
        self.assertEqual(result.failed_target_ids, (31,))
        self.repository.update_case_status.assert_any_await(7, "completed")
        self.repository.update_case_status.assert_any_await(8, "failed")

    async def test_massban_rejects_duplicate_and_over_limit_targets_before_actions(self) -> None:
        with self.assertRaisesRegex(ValueError, "targets must be unique"):
            await self.service.massban_members(
                guild=self.guild,
                targets=[self.target, self.target],
                moderator=self.moderator,
                bot_member=self.bot_member,
            )
        self.target.ban.assert_not_awaited()
        too_many = [
            SimpleNamespace(
                id=100 + index,
                guild=self.guild,
                top_role=SimpleNamespace(position=1),
                ban=AsyncMock(),
            )
            for index in range(11)
        ]
        with self.assertRaisesRegex(ValueError, "between 2 and 10"):
            await self.service.massban_members(
                guild=self.guild,
                targets=too_many,
                moderator=self.moderator,
                bot_member=self.bot_member,
            )
        for target in too_many:
            target.ban.assert_not_awaited()

    async def test_masskick_returns_actual_success_and_failure_counts(self) -> None:
        self.moderator.guild_permissions.kick_members = True
        self.bot_member.guild_permissions.kick_members = True
        self.repository.create_case.side_effect = [
            case_record("masskick"),
            ModerationCase(
                case_id=8,
                guild_id=1,
                target_id=31,
                moderator_id=10,
                action_type="masskick",
                reason="Raid",
                created_at="2026-01-01T00:00:00+00:00",
                expires_at=None,
                status="pending",
            ),
        ]
        second = SimpleNamespace(
            id=31,
            guild=self.guild,
            top_role=SimpleNamespace(position=1),
            kick=AsyncMock(side_effect=RuntimeError("discord rejected this target")),
        )
        result = await self.service.masskick_members(
            guild=self.guild,
            targets=[self.target, second],
            moderator=self.moderator,
            bot_member=self.bot_member,
            reason="Raid",
        )
        self.assertEqual(result.completed_target_ids, (30,))
        self.assertEqual(result.failed_target_ids, (31,))
        self.target.kick.assert_awaited_once_with(reason="Case #7: Raid")
        self.repository.update_case_status.assert_any_await(7, "completed")
        self.repository.update_case_status.assert_any_await(8, "failed")


if __name__ == "__main__":
    unittest.main()
