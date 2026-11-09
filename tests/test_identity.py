from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

from discord.ext import commands

from cogs.owner import OwnerCog
from core.bot import AegisBot
from core.configuration import get_default_prefix, get_invite_url, get_owner_id, get_support_url
from database.repositories.community import CommunityRepository


class ConfigurationTests(unittest.TestCase):
    def test_default_prefix_and_owner_are_environment_backed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_default_prefix(), "a!")
            self.assertIsNone(get_owner_id())
        with patch.dict(
            os.environ,
            {
                "AEGIS_PREFIX": "a?",
                "OWNER_ID": "42",
            },
            clear=True,
        ):
            self.assertEqual(get_default_prefix(), "a?")
            self.assertEqual(get_owner_id(), 42)

    def test_invalid_owner_prefix_and_unconfigured_brand_urls_are_safe(self) -> None:
        with patch.dict(os.environ, {"OWNER_ID": "not-an-id"}, clear=True):
            with self.assertRaises(ValueError):
                get_owner_id()
        with patch.dict(os.environ, {"AEGIS_PREFIX": "two words"}, clear=True):
            with self.assertRaises(ValueError):
                get_default_prefix()
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(get_support_url())
            self.assertIsNone(get_invite_url())


class PrefixAndNoPrefixPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "aegis.sqlite3"
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.temp_dir.cleanup()

    async def test_prefix_and_no_prefix_access_survive_database_reopen(self) -> None:
        self.assertEqual(
            await self.repository.get_guild_prefix(10, default_prefix="a!"),
            "a!",
        )
        self.assertEqual(
            await self.repository.set_guild_prefix(guild_id=10, prefix="?"),
            "?",
        )
        self.assertTrue(
            await self.repository.add_no_prefix_user(user_id=20, added_by=30)
        )
        self.assertFalse(
            await self.repository.add_no_prefix_user(user_id=20, added_by=30)
        )
        self.assertTrue(await self.repository.has_no_prefix_user(20))
        await self.repository.close()
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()

        self.assertEqual(
            await self.repository.get_guild_prefix(10, default_prefix="a!"),
            "?",
        )
        self.assertEqual(await self.repository.list_no_prefix_users(), [20])
        self.assertTrue(await self.repository.remove_no_prefix_user(user_id=20))
        self.assertFalse(await self.repository.has_no_prefix_user(20))

    async def test_invalid_prefixes_and_ids_are_rejected(self) -> None:
        for prefix in ("", "two words", "<@123>", "x" * 17):
            with self.subTest(prefix=prefix):
                with self.assertRaises(ValueError):
                    await self.repository.set_guild_prefix(guild_id=10, prefix=prefix)
        for user_id in (0, -1, True, 9_223_372_036_854_775_808):
            with self.subTest(user_id=user_id):
                with self.assertRaises(ValueError):
                    await self.repository.add_no_prefix_user(
                        user_id=user_id,
                        added_by=30,
                    )

    async def test_bot_prefix_callback_only_adds_empty_prefix_for_authorized_users(self) -> None:
        bot = AegisBot(database_path=":memory:")
        repository = SimpleNamespace(
            get_guild_prefix=AsyncMock(return_value="?"),
            has_no_prefix_user=AsyncMock(return_value=False),
            close=AsyncMock(),
        )
        bot.community_repository = repository
        message = SimpleNamespace(
            guild=SimpleNamespace(id=10),
            author=SimpleNamespace(id=20),
        )
        prefix_factory = lambda _bot, _message: ["<@999> ", "<@!999> ", "?"]
        try:
            with patch("core.bot.commands.when_mentioned_or", return_value=prefix_factory):
                self.assertEqual(
                    await bot.get_prefix(message),
                    ["<@999> ", "<@!999> ", "?"],
                )
                repository.has_no_prefix_user.assert_awaited_once_with(20)

            repository.has_no_prefix_user.return_value = True
            with patch("core.bot.commands.when_mentioned_or", return_value=prefix_factory):
                self.assertEqual(
                    await bot.get_prefix(message),
                    ["<@999> ", "<@!999> ", "?", ""],
                )
        finally:
            await bot.close()

    async def test_mention_only_response_supports_nickname_mention_and_ignores_text(self) -> None:
        bot = AegisBot(database_path=":memory:")
        bot.default_prefix = "?"
        send = AsyncMock()
        mention = SimpleNamespace(id=999)
        try:
            with patch.object(
                AegisBot,
                "user",
                new_callable=PropertyMock,
                return_value=SimpleNamespace(id=999),
            ):
                for content in ("<@999>", "<@!999>"):
                    message = SimpleNamespace(
                        mentions=[mention],
                        content=content,
                        guild=None,
                        channel=SimpleNamespace(send=send),
                    )
                    self.assertTrue(await bot._reply_to_mention_only(message))

                unrelated = SimpleNamespace(
                    mentions=[mention],
                    content="hello <@999>",
                    guild=None,
                    channel=SimpleNamespace(send=send),
                )
                self.assertFalse(await bot._reply_to_mention_only(unrelated))
            self.assertEqual(send.await_count, 2)
            self.assertEqual(send.await_args.kwargs["allowed_mentions"].everyone, False)
        finally:
            await bot.close()

    async def test_owner_check_uses_only_the_configured_id_not_staff_permissions(self) -> None:
        with patch.dict(os.environ, {"OWNER_ID": "42"}):
            bot = AegisBot(database_path=":memory:")
        self.assertTrue(await bot.is_owner(SimpleNamespace(id=42)))
        self.assertFalse(await bot.is_owner(SimpleNamespace(id=43)))

        ctx = SimpleNamespace(
            bot=SimpleNamespace(is_owner=AsyncMock(return_value=False)),
            author=SimpleNamespace(id=43, guild_permissions=SimpleNamespace(administrator=True)),
        )
        owner_check = OwnerCog.noprefix_add.checks[0]
        with self.assertRaises(commands.NotOwner):
            await owner_check(ctx)
        ctx.bot.is_owner.return_value = True
        self.assertTrue(await owner_check(ctx))
        await bot.close()


if __name__ == "__main__":
    unittest.main()
