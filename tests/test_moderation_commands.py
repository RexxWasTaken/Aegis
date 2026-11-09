from __future__ import annotations

import unittest

import discord
from discord.ext import commands

from core.bot import AegisBot
from core.loader import load_extensions
from database.repositories.community import CommunityRepository


MODERATION_COMMANDS = {
    "ban", "unban", "softban", "tempban", "massban",
    "lock", "unlock", "lockall", "unlockall", "slowmode",
    "jail", "unjail", "kick", "masskick", "nick", "resetnick",
    "purge", "purgeuser", "purgebots", "purgehumans", "purgelinks",
    "purgeinvites", "purgeimages", "purgefiles", "purgeembeds",
    "purgementions", "purgecontains", "purgeafter", "timeout",
    "untimeout", "mute", "unmute", "voicemute", "voiceunmute",
    "deafen", "undeafen", "disconnect", "move", "warn", "unwarn",
    "warninfo", "warnings", "warnlist", "warnstats", "clearwarnings",
}
COMMUNITY_COMMANDS = {
    "help",
    "ticket",
    "giveaway",
}
MUSIC_COMMANDS = {
    "play",
    "pause",
    "resume",
    "skip",
    "stop",
    "queue",
    "nowplaying",
    "volume",
    "loop",
    "shuffle",
    "lyrics",
    "seek",
    "remove",
    "clear",
    "join",
    "leave",
    "previous",
    "autoplay",
}
EXPECTED_COMMANDS = MODERATION_COMMANDS | COMMUNITY_COMMANDS | MUSIC_COMMANDS


class ModerationCommandRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_moderation_and_community_commands_register_without_duplicates(self) -> None:
        bot = commands.Bot(
            command_prefix="a!",
            intents=discord.Intents.none(),
            help_command=None,
        )
        bot.moderation_service = object()
        community_repository = CommunityRepository(":memory:")
        await community_repository.initialize()
        bot.community_repository = community_repository
        try:
            await load_extensions(bot)
            self.assertEqual(
                {command.name for command in bot.commands}, EXPECTED_COMMANDS
            )
            registered_names = [command.qualified_name for command in bot.walk_commands()]
            self.assertEqual(len(registered_names), len(set(registered_names)))
            self.assertIs(bot.get_command("b"), bot.get_command("ban"))
            self.assertIs(bot.get_command("ub"), bot.get_command("unban"))
            self.assertIs(bot.get_command("k"), bot.get_command("kick"))
            self.assertEqual(bot.get_command("ban").qualified_name, "ban")
            self.assertEqual(bot.get_command("unban").qualified_name, "unban")
            for command_name in (
                "ticket panel",
                "ticket setup",
                "ticket close",
                "ticket reopen",
                "ticket claim",
                "ticket delete",
                "ticket add",
                "ticket remove",
                "ticket transcript",
                "ticket info",
                "giveaway start",
                "giveaway end",
                "giveaway reroll",
                "giveaway list",
                "giveaway delete",
                "giveaway pause",
                "giveaway resume",
            ):
                self.assertIn(command_name, registered_names)
            from core.help_view import discover_commands

            discovered = discover_commands(bot)
            for mode in ("prefix", "slash"):
                names = {
                    entry.qualified_name
                    for entries in discovered[mode].values()
                    for entry in entries
                }
                self.assertFalse(any(name.endswith("help") for name in names))
                self.assertIn("Ticket", discovered[mode])
                self.assertIn("Giveaway", discovered[mode])
                self.assertIn("Music", discovered[mode])
            self.assertTrue(
                any(
                    entry.usage.startswith("a!ticket")
                    for entries in discovered["prefix"].values()
                    for entry in entries
                )
            )
            self.assertTrue(
                any(
                    entry.usage.startswith("/giveaway")
                    for entries in discovered["slash"].values()
                    for entry in entries
                )
            )
        finally:
            giveaway_cog = bot.get_cog("GiveawayCog")
            if giveaway_cog is not None:
                giveaway_cog.expire_due_giveaways.cancel()
            music_events = bot.get_cog("MusicPlayerEvents")
            if music_events is not None:
                music_events.refresh_music_panels.cancel()
            await community_repository.close()
            await bot.close()

    async def test_application_setup_initializes_database_cogs_and_expiry_worker(self) -> None:
        bot = AegisBot(database_path=":memory:")
        try:
            await bot.setup_hook()
            self.assertIsNotNone(bot.moderation_repository)
            self.assertIsNotNone(bot.moderation_service)
            self.assertIsNotNone(bot.community_repository)
            self.assertEqual(
                {command.name for command in bot.commands}, EXPECTED_COMMANDS
            )
            self.assertEqual(
                {command.name for command in bot.tree.get_commands()},
                COMMUNITY_COMMANDS | MUSIC_COMMANDS,
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
