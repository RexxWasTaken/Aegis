from __future__ import annotations

import unittest

import discord
from discord.ext import commands

from core.bot import AegisBot


class ModerationCommandRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_moderation_extensions_register_first_fourteen_commands_and_aliases(self) -> None:
        bot = commands.Bot(
            command_prefix="a!",
            intents=discord.Intents.none(),
            help_command=None,
        )
        bot.moderation_service = object()
        try:
            await bot.load_extension("cogs.moderation.bans")
            await bot.load_extension("cogs.moderation.kicks")
            await bot.load_extension("cogs.moderation.timeouts")
            await bot.load_extension("cogs.moderation.voice_moderation")
            self.assertEqual(
                {command.name for command in bot.commands},
                {
                    "ban", "unban", "softban", "tempban", "massban", "kick",
                    "masskick", "timeout", "untimeout", "mute", "unmute",
                    "voicemute", "voiceunmute", "deafen",
                },
            )
            self.assertIs(bot.get_command("b"), bot.get_command("ban"))
            self.assertIs(bot.get_command("ub"), bot.get_command("unban"))
            self.assertIs(bot.get_command("k"), bot.get_command("kick"))
            self.assertEqual(bot.get_command("ban").qualified_name, "ban")
            self.assertEqual(bot.get_command("unban").qualified_name, "unban")
        finally:
            await bot.close()

    async def test_application_setup_initializes_database_cogs_and_expiry_worker(self) -> None:
        bot = AegisBot(database_path=":memory:")
        try:
            await bot.setup_hook()
            self.assertIsNotNone(bot.moderation_repository)
            self.assertIsNotNone(bot.moderation_service)
            self.assertEqual(
                {command.name for command in bot.commands},
                {
                    "ban", "unban", "softban", "tempban", "massban", "kick",
                    "masskick", "timeout", "untimeout", "mute", "unmute",
                    "voicemute", "voiceunmute", "deafen",
                },
            )
            self.assertIsNotNone(bot.tempban_expiry_task)
            self.assertTrue(bot.tempban_expiry_task.run.is_running())
        finally:
            await bot.close()

    async def test_massban_parser_and_confirmation_view(self) -> None:
        from cogs.moderation.utilities import (
            BulkActionConfirmationView,
            parse_bulk_member_arguments,
        )

        tokens, reason = parse_bulk_member_arguments(
            "<@111111111111111111> 222222222222222222 coordinated raid",
            "massban",
        )
        self.assertEqual(len(tokens), 2)
        self.assertEqual(reason, "coordinated raid")
        with self.assertRaises(commands.BadArgument):
            parse_bulk_member_arguments("111111111111111111", "massban")
        kick_tokens, kick_reason = parse_bulk_member_arguments(
            "111111111111111111 222222222222222222 cleanup",
            "masskick",
        )
        self.assertEqual(len(kick_tokens), 2)
        self.assertEqual(kick_reason, "cleanup")
        view = BulkActionConfirmationView(author_id=10)
        self.assertEqual([button.label for button in view.children], ["Confirm", "Cancel"])


if __name__ == "__main__":
    unittest.main()
