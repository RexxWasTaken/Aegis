from __future__ import annotations

import unittest
from types import SimpleNamespace

import discord

from core.emoji_manager import EMOJI_IDS, emoji_markup
from embeds.moderation import (
    COMMAND_SPECS,
    ERROR_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
    confirmation_embed,
    success_embed,
)
from embeds.moderation_errors import missing_permissions_embed, wrong_usage_embed


EXPECTED_COMMANDS = {
    "ban", "unban", "softban", "tempban", "kick", "massban", "masskick",
    "timeout", "untimeout", "mute", "unmute", "voicemute", "voiceunmute",
    "deafen", "undeafen", "disconnect", "move", "warn", "unwarn", "warnings",
    "clearwarnings", "warninfo", "warnlist", "warnstats", "purge", "purgeuser",
    "purgebots", "purgehumans", "purgelinks", "purgeinvites", "purgeimages",
    "purgefiles", "purgeembeds", "purgementions", "purgecontains", "purgeafter",
    "lock", "unlock", "lockall", "unlockall", "slowmode", "nick", "resetnick",
    "jail", "unjail",
}


class ModerationEmbedTests(unittest.TestCase):
    def test_exactly_45_unique_command_previews_exist(self) -> None:
        self.assertEqual(len(COMMAND_SPECS), 45)
        self.assertEqual(set(COMMAND_SPECS), EXPECTED_COMMANDS)

    def test_every_command_has_success_usage_and_permission_embeds(self) -> None:
        for name in COMMAND_SPECS:
            with self.subTest(command=name):
                success = success_embed(name)
                usage = wrong_usage_embed(name)
                permission = missing_permissions_embed(name)
                self.assertIsInstance(success, discord.Embed)
                self.assertIsInstance(usage, discord.Embed)
                self.assertIsInstance(permission, discord.Embed)
                self.assertEqual(success.color, SUCCESS_COLOR)
                self.assertEqual(usage.color, ERROR_COLOR)
                self.assertEqual(permission.color, ERROR_COLOR)
                self.assertIn(COMMAND_SPECS[name].usage, usage.description)
                self.assertIn("required permissions", permission.description)

    def test_risky_bulk_commands_have_confirmation_embeds(self) -> None:
        expected = {
            "massban", "masskick", "clearwarnings", "purge", "purgeuser",
            "purgebots", "purgehumans", "purgelinks", "purgeinvites",
            "purgeimages", "purgefiles", "purgeembeds", "purgementions",
            "purgecontains", "purgeafter", "lockall", "unlockall",
        }
        actual = {
            name for name, spec in COMMAND_SPECS.items()
            if spec.confirmation_title is not None
        }
        self.assertEqual(actual, expected)
        for name in expected:
            with self.subTest(command=name):
                embed = confirmation_embed(name)
                self.assertIsInstance(embed, discord.Embed)
                self.assertEqual(embed.color, WARNING_COLOR)
                self.assertIn(emoji_markup("warning"), embed.title)

    def test_requested_examples_match_the_spec(self) -> None:
        ban = success_embed("ban")
        timeout = success_embed("timeout")
        kick = success_embed("kick")
        purge = success_embed("purge")
        self.assertIn("Banned", ban.title)
        self.assertEqual(ban.description, "> Reason: Breaking rules")
        self.assertIn("Duration: 10 minutes", timeout.description)
        self.assertIn("Reason: Spamming", timeout.description)
        self.assertIn("Kicked", kick.title)
        self.assertIn("Successfully deleted 50 messages", purge.title)

    def test_ban_and_unban_success_embeds_use_the_real_target_and_reason(self) -> None:
        target = SimpleNamespace(id=123, mention="<@123>")
        ban = success_embed("ban", target=target, reason="Reviewed")
        unban = success_embed("unban", target=target, reason="Appeal accepted")
        self.assertIn("<@123>", ban.title)
        self.assertEqual(ban.description, "> Reason: Reviewed")
        self.assertIn("<@123>", unban.title)
        self.assertEqual(unban.description, "> Reason: Appeal accepted")

    def test_tempban_embed_uses_the_parsed_duration(self) -> None:
        target = SimpleNamespace(id=123, mention="<@123>")
        embed = success_embed("tempban", target=target, reason="Spamming", duration="2 hours")
        self.assertIn("<@123>", embed.title)
        self.assertIn("> Duration: 2 hours", embed.description)
        self.assertIn("> Reason: Spamming", embed.description)

    def test_timeout_embed_uses_the_actual_duration(self) -> None:
        target = SimpleNamespace(id=123, mention="<@123>")
        embed = success_embed("timeout", target=target, reason="Spamming", duration="20 minutes")
        self.assertIn("<@123>", embed.title)
        self.assertIn("> Duration: 20 minutes", embed.description)
        self.assertIn("> Reason: Spamming", embed.description)

    def test_voice_success_embeds_include_the_custom_voice_marker(self) -> None:
        for name in ("voicemute", "voiceunmute", "deafen", "undeafen", "disconnect", "move"):
            with self.subTest(command=name):
                self.assertIn(emoji_markup("voice"), success_embed(name).title)

    def test_massban_preview_uses_actual_target_count(self) -> None:
        confirmation = confirmation_embed("massban", count=3)
        success = success_embed("massban", count=2, total=3)
        self.assertEqual(confirmation.description, "You are about to ban 3 members.")
        self.assertIn("Banned 2 of 3 members", success.title)

    def test_masskick_preview_uses_actual_target_count(self) -> None:
        confirmation = confirmation_embed("masskick", count=4)
        success = success_embed("masskick", count=3, total=4)
        self.assertEqual(confirmation.description, "You are about to kick 4 members.")
        self.assertIn("Kicked 3 of 4 members", success.title)

    def test_custom_emoji_catalog_and_unknown_handling(self) -> None:
        self.assertEqual(len(EMOJI_IDS), 40)
        self.assertEqual(emoji_markup("success"), "<:success:1518658821650776225>")
        self.assertEqual(emoji_markup("not-a-configured-emoji"), "")


if __name__ == "__main__":
    unittest.main()
