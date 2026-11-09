from __future__ import annotations

import unittest

import discord
from discord.ext import commands

from cogs.fun import FunCog
from cogs.games import GamesCog
from cogs.information import InformationCog
from cogs.moderation.voice_moderation import VoiceModerationCog
from cogs.utility import UtilityCog
from core.help_view import discover_commands, find_command


class NewCategoryCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = commands.Bot(
            command_prefix="a!",
            intents=discord.Intents.none(),
            help_command=None,
        )
        await self.bot.add_cog(UtilityCog(self.bot))
        await self.bot.add_cog(InformationCog())
        await self.bot.add_cog(FunCog())
        await self.bot.add_cog(GamesCog())
        await self.bot.add_cog(VoiceModerationCog(self.bot))

    async def asyncTearDown(self) -> None:
        await self.bot.close()

    async def test_commands_are_registered_once_and_in_their_help_categories(self) -> None:
        prefix_registry = discover_commands(self.bot)["prefix"]
        slash_registry = discover_commands(self.bot)["slash"]

        expected = {
            "Utility": {"prefix", "setprefix", "ping", "support", "invite"},
            "Information": {"userinfo", "serverinfo", "avatar"},
            "Fun": {"coinflip", "eightball", "choose"},
            "Games": {"rps", "roll"},
        }
        for registry in (prefix_registry, slash_registry):
            for category, names in expected.items():
                self.assertEqual(
                    {entry.qualified_name for entry in registry[category]},
                    names,
                )
        self.assertEqual(
            {entry.qualified_name for entry in prefix_registry["Voice"]},
            {"voicemute", "voiceunmute", "deafen", "undeafen", "disconnect", "move"},
        )
        self.assertNotIn("Voice", slash_registry)
        self.assertEqual(
            len([command.qualified_name for command in self.bot.walk_commands()]),
            len({command.qualified_name for command in self.bot.walk_commands()}),
        )

    async def test_help_usage_uses_the_custom_prefix_for_discovery_and_lookup(self) -> None:
        registry = discover_commands(self.bot, prefix="?")
        prefix_command = next(
            entry for entry in registry["prefix"]["Utility"]
            if entry.qualified_name == "prefix"
        )
        self.assertEqual(prefix_command.usage, "?prefix")
        details = find_command(self.bot, "?setprefix", prefix="?")
        self.assertIsNotNone(details)
        self.assertEqual(details.usage, "?setprefix <prefix>")


if __name__ == "__main__":
    unittest.main()
