from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.moderation.voice_moderation import VoiceModerationCog
from cogs.moderation.warnings import WarningCog
from database.repositories.moderation import ModerationWarning


class BatchOneCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot_member = SimpleNamespace(id=20)
        self.guild = SimpleNamespace(id=1, me=self.bot_member)
        self.author = SimpleNamespace(id=10)
        self.service = AsyncMock()
        self.bot = SimpleNamespace(moderation_service=self.service)
        self.ctx = SimpleNamespace(
            guild=self.guild,
            author=self.author,
            send=AsyncMock(),
        )
        self.source = SimpleNamespace(id=40, mention="<#40>")
        self.target = SimpleNamespace(
            id=30,
            mention="<@30>",
            voice=SimpleNamespace(channel=self.source),
        )

    async def test_undeafen_disconnect_and_move_forward_to_service(self) -> None:
        voice_cog = VoiceModerationCog(self.bot)
        self.service.undeafen_member.return_value = SimpleNamespace(reason="reviewed")
        await VoiceModerationCog.undeafen.callback(
            voice_cog, self.ctx, self.target, reason="reviewed"
        )
        self.service.undeafen_member.assert_awaited_once_with(
            guild=self.guild,
            target=self.target,
            moderator=self.author,
            bot_member=self.bot_member,
            reason="reviewed",
        )
        self.assertIn("Undeafened", self.ctx.send.await_args.kwargs["embed"].description)

        self.ctx.send.reset_mock()
        self.service.disconnect_member.return_value = SimpleNamespace(reason="cleanup")
        await VoiceModerationCog.disconnect.callback(
            voice_cog, self.ctx, self.target, reason="cleanup"
        )
        self.service.disconnect_member.assert_awaited_once_with(
            guild=self.guild,
            target=self.target,
            moderator=self.author,
            bot_member=self.bot_member,
            reason="cleanup",
        )
        self.assertIn("Disconnected", self.ctx.send.await_args.kwargs["embed"].description)

        self.ctx.send.reset_mock()
        destination = SimpleNamespace(id=50, mention="<#50>")
        self.service.move_member.return_value = SimpleNamespace(reason="move")
        await VoiceModerationCog.move.callback(
            voice_cog, self.ctx, self.target, destination, reason="move"
        )
        self.service.move_member.assert_awaited_once_with(
            guild=self.guild,
            target=self.target,
            destination=destination,
            moderator=self.author,
            bot_member=self.bot_member,
            reason="move",
        )
        embed = self.ctx.send.await_args.kwargs["embed"]
        self.assertIn("<#40>", embed.description)
        self.assertIn("<#50>", embed.description)

    async def test_warn_unwarn_and_warnings_use_persisted_service_results(self) -> None:
        warning_cog = WarningCog(self.bot)
        warning = ModerationWarning(
            warning_id=104,
            guild_id=1,
            target_id=30,
            moderator_id=10,
            reason="repeated spam",
            created_at="2026-01-01T00:00:00+00:00",
        )
        self.service.warn_member.return_value = warning
        await WarningCog.warn.callback(
            warning_cog, self.ctx, self.target, reason="repeated spam"
        )
        self.service.warn_member.assert_awaited_once_with(
            guild=self.guild,
            target=self.target,
            moderator=self.author,
            reason="repeated spam",
        )
        self.assertIn("#104", self.ctx.send.await_args.kwargs["embed"].description)

        self.ctx.send.reset_mock()
        self.service.remove_warning.return_value = warning
        await WarningCog.unwarn.callback(
            warning_cog, self.ctx, self.target, warning_id=104
        )
        self.service.remove_warning.assert_awaited_once_with(
            guild=self.guild,
            target=self.target,
            warning_id=104,
            moderator=self.author,
        )
        self.assertIn("#104", self.ctx.send.await_args.kwargs["embed"].description)

        self.ctx.send.reset_mock()
        self.service.warnings_for_member.return_value = [warning]
        await WarningCog.warnings.callback(warning_cog, self.ctx, self.target)
        self.service.warnings_for_member.assert_awaited_once_with(
            guild=self.guild,
            target=self.target,
            moderator=self.author,
        )
        self.assertIn("Active warnings: 1", self.ctx.send.await_args.kwargs["embed"].description)

    async def test_clearwarnings_deletes_only_after_confirmation(self) -> None:
        warning_cog = WarningCog(self.bot)
        warning = ModerationWarning(
            warning_id=104,
            guild_id=1,
            target_id=30,
            moderator_id=10,
            reason="repeated spam",
            created_at="2026-01-01T00:00:00+00:00",
        )
        self.service.warnings_for_member.return_value = [warning]
        self.service.clear_warnings_for_member.return_value = 1
        confirmation_message = SimpleNamespace(edit=AsyncMock())

        class ConfirmingView:
            def __init__(self, author_id: int) -> None:
                self.author_id = author_id
                self.value = True

            async def wait(self) -> None:
                return None

        self.ctx.send.return_value = confirmation_message
        with patch(
            "cogs.moderation.warnings.BulkActionConfirmationView",
            ConfirmingView,
        ):
            await WarningCog.clearwarnings.callback(
                warning_cog, self.ctx, self.target
            )

        self.service.clear_warnings_for_member.assert_awaited_once_with(
            guild=self.guild,
            target=self.target,
            moderator=self.author,
        )
        confirmation_message.edit.assert_awaited_once_with(view=None)
        self.assertEqual(self.ctx.send.await_count, 2)
        self.assertIn(
            "Warnings removed: 1",
            self.ctx.send.await_args.kwargs["embed"].description,
        )

    async def test_clearwarnings_cancel_path_does_not_delete_records(self) -> None:
        warning_cog = WarningCog(self.bot)
        self.service.warnings_for_member.return_value = [
            SimpleNamespace(warning_id=104)
        ]
        confirmation_message = SimpleNamespace(edit=AsyncMock())

        class CancellingView:
            def __init__(self, author_id: int) -> None:
                self.author_id = author_id
                self.value = False

            async def wait(self) -> None:
                return None

        self.ctx.send.return_value = confirmation_message
        with patch(
            "cogs.moderation.warnings.BulkActionConfirmationView",
            CancellingView,
        ):
            await WarningCog.clearwarnings.callback(
                warning_cog, self.ctx, self.target
            )

        self.service.clear_warnings_for_member.assert_not_awaited()
        confirmation_message.edit.assert_awaited_once_with(view=None)
        self.assertIn(
            "cancelled",
            self.ctx.send.await_args.kwargs["embed"].description.lower(),
        )


if __name__ == "__main__":
    unittest.main()
