from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
from discord.ext import commands

from cogs.moderation.purge import PurgeCog, contains_link
from cogs.moderation.warnings import WarningCog
from database.repositories.moderation import ModerationWarning, WarningStats


class FakeChannel:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self.id = 70
        self.messages = messages
        self.deleted_ids: list[int] = []
        self.bulk_calls: list[list[int]] = []

    def permissions_for(self, member: object) -> SimpleNamespace:
        return SimpleNamespace(
            view_channel=True,
            read_message_history=True,
            manage_messages=True,
        )

    async def history(self, *, limit: int):
        for message in self.messages[:limit]:
            yield message

    async def delete_messages(self, messages, *, reason: str) -> None:
        ids = [message.id for message in messages]
        self.bulk_calls.append(ids)
        self.deleted_ids.extend(ids)


def make_message(
    message_id: int,
    *,
    author_id: int = 30,
    bot: bool = False,
    content: str = "ordinary conversation",
    days_old: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=message_id,
        author=SimpleNamespace(id=author_id, bot=bot),
        content=content,
        created_at=datetime.now(timezone.utc) - timedelta(days=days_old),
        delete=AsyncMock(),
    )


class BatchTwoCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bot_member = SimpleNamespace(id=20)
        self.guild = SimpleNamespace(id=1, me=self.bot_member)
        self.author = SimpleNamespace(id=10)
        self.service = AsyncMock()
        self.bot = SimpleNamespace(moderation_service=self.service, user=None)
        self.target = SimpleNamespace(id=30, mention="<@30>")

    def make_purge_context(
        self, messages: list[SimpleNamespace]
    ) -> tuple[SimpleNamespace, FakeChannel, SimpleNamespace]:
        channel = FakeChannel(messages)
        confirmation = SimpleNamespace(edit=AsyncMock())
        ctx = SimpleNamespace(
            guild=self.guild,
            channel=channel,
            message=SimpleNamespace(id=999),
            author=self.author,
            command=SimpleNamespace(name="purge"),
            send=AsyncMock(return_value=confirmation),
        )
        return ctx, channel, confirmation

    async def test_warnlist_pages_real_records_and_warnstats_uses_stored_totals(self) -> None:
        warning = ModerationWarning(
            warning_id=104,
            guild_id=1,
            target_id=30,
            moderator_id=10,
            reason="Repeated spam",
            created_at="2026-01-01T00:00:00+00:00",
        )
        self.service.warning_page.return_value = ([warning], 17)
        cog = WarningCog(self.bot)
        ctx = SimpleNamespace(guild=self.guild, author=self.author, send=AsyncMock())

        await WarningCog.warnlist.callback(cog, ctx, self.target)
        self.service.warning_page.assert_awaited_once_with(
            guild=self.guild,
            moderator=self.author,
            target=self.target,
            limit=8,
            offset=0,
        )
        first_embed = ctx.send.await_args.kwargs["embed"]
        view = ctx.send.await_args.kwargs["view"]
        self.assertIn("Page: 1 of 3", first_embed.description)
        self.assertIsNotNone(view)

        response = SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock())
        interaction = SimpleNamespace(
            user=self.author,
            response=response,
        )
        await view._show_page(interaction, 1)
        self.assertEqual(view.page, 2)
        self.service.warning_page.assert_awaited_with(
            guild=self.guild,
            moderator=self.author,
            target=self.target,
            limit=8,
            offset=8,
        )
        self.assertIn("Page: 2 of 3", response.edit_message.await_args.kwargs["embed"].description)

        self.service.warning_statistics.return_value = WarningStats(
            total_warnings=17,
            members_warned=9,
            moderators_with_warnings=3,
        )
        ctx.send.reset_mock()
        await WarningCog.warnstats.callback(cog, ctx)
        self.service.warning_statistics.assert_awaited_once_with(
            guild=self.guild, moderator=self.author
        )
        self.assertIn(
            "Total warnings: 17",
            ctx.send.await_args.kwargs["embed"].description,
        )

    async def test_all_five_purge_commands_apply_their_own_filters(self) -> None:
        cog = PurgeCog(self.bot)
        cases = [
            (
                "purge",
                [make_message(1), make_message(2), make_message(3)],
                (),
                {1, 2},
            ),
            (
                "purgeuser",
                [
                    make_message(11, author_id=30),
                    make_message(12, author_id=40),
                    make_message(13, author_id=30),
                ],
                (self.target,),
                {11, 13},
            ),
            (
                "purgebots",
                [
                    make_message(21, author_id=50, bot=True),
                    make_message(22, author_id=30),
                    make_message(23, author_id=51, bot=True),
                ],
                (),
                {21, 23},
            ),
            (
                "purgehumans",
                [
                    make_message(31, author_id=30),
                    make_message(32, author_id=50, bot=True),
                    make_message(33, author_id=40),
                ],
                (),
                {31, 33},
            ),
            (
                "purgelinks",
                [
                    make_message(41, content="https://example.com/a"),
                    make_message(42, content="normal message without a URL"),
                    make_message(43, content="discord.gg/invite-code"),
                ],
                (),
                {41, 43},
            ),
        ]

        class ConfirmingView:
            def __init__(self, author_id: int) -> None:
                self.author_id = author_id
                self.value = True

            async def wait(self) -> None:
                return None

        with patch("cogs.moderation.purge.BulkActionConfirmationView", ConfirmingView):
            for name, messages, args, expected_ids in cases:
                with self.subTest(command=name):
                    ctx, channel, _ = self.make_purge_context(messages)
                    command = getattr(PurgeCog, name)
                    await command.callback(cog, ctx, *args, 2)
                    self.assertEqual(set(channel.deleted_ids), expected_ids)
                    self.assertEqual(
                        ctx.send.await_args.kwargs["embed"].description,
                        None,
                    )

    async def test_purge_excludes_invocation_and_deletes_old_messages_singly(self) -> None:
        cog = PurgeCog(self.bot)
        recent_one = make_message(51)
        recent_two = make_message(52)
        old_message = make_message(53, days_old=15)
        invocation = make_message(999)
        ctx, channel, confirmation = self.make_purge_context(
            [recent_one, invocation, recent_two, old_message]
        )

        class ConfirmingView:
            def __init__(self, author_id: int) -> None:
                self.value = True

            async def wait(self) -> None:
                return None

        with patch("cogs.moderation.purge.BulkActionConfirmationView", ConfirmingView):
            await PurgeCog.purge.callback(cog, ctx, 3)

        self.assertEqual(channel.bulk_calls, [[51, 52]])
        old_message.delete.assert_awaited_once()
        self.assertIn("Successfully deleted 3 messages", ctx.send.await_args.kwargs["embed"].title)
        confirmation.edit.assert_awaited_once_with(view=None)

    async def test_purge_cancel_and_invalid_count_never_delete(self) -> None:
        cog = PurgeCog(self.bot)
        message = make_message(61)
        ctx, channel, confirmation = self.make_purge_context([message])

        class CancellingView:
            def __init__(self, author_id: int) -> None:
                self.value = False

            async def wait(self) -> None:
                return None

        with patch("cogs.moderation.purge.BulkActionConfirmationView", CancellingView):
            await PurgeCog.purge.callback(cog, ctx, 1)
        self.assertEqual(channel.deleted_ids, [])
        message.delete.assert_not_awaited()
        self.assertIn("cancelled", ctx.send.await_args.kwargs["embed"].description.lower())

        with self.assertRaises(commands.BadArgument):
            await PurgeCog.purge.callback(cog, ctx, 101)
        self.assertEqual(channel.deleted_ids, [])

    async def test_purge_requires_bot_channel_permissions_before_confirmation(self) -> None:
        cog = PurgeCog(self.bot)
        ctx, channel, _ = self.make_purge_context([make_message(71)])
        channel.permissions_for = lambda member: SimpleNamespace(
            view_channel=True,
            read_message_history=True,
            manage_messages=False,
        )
        with self.assertRaises(commands.BotMissingPermissions):
            await PurgeCog.purge.callback(cog, ctx, 1)
        ctx.send.assert_not_awaited()
        self.assertEqual(channel.deleted_ids, [])

    async def test_link_detector_matches_links_without_matching_plain_text_or_email(self) -> None:
        for content in (
            "https://example.com/path",
            "www.example.org",
            "discord.gg/invite-code",
            "example.net",
        ):
            with self.subTest(content=content):
                self.assertTrue(contains_link(content))
        for content in (
            "This is an ordinary sentence about the internet.",
            "my email is member@example.com",
            "I do not like spam",
        ):
            with self.subTest(content=content):
                self.assertFalse(contains_link(content))


if __name__ == "__main__":
    unittest.main()
