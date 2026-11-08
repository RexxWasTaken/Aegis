from __future__ import annotations

import unittest
from types import SimpleNamespace

import discord

import core.emoji_manager as emoji_manager_module

from core.emoji_manager import EMOJI_IDS, emoji_for, emoji_markup
from database.repositories.moderation import ModerationWarning, WarningStats
from embeds.moderation import (
    COMMAND_SPECS,
    ERROR_COLOR,
    SUCCESS_COLOR,
    WARNING_COLOR,
    confirmation_embed,
    success_embed,
    warning_history_embeds,
    warning_list_embed,
    warning_stats_embed,
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
                self.assertIsNone(success.title)
                self.assertTrue(success.description.startswith(emoji_markup("success")))
                self.assertEqual(usage.color, ERROR_COLOR)
                self.assertEqual(permission.color, ERROR_COLOR)
                self.assertTrue(usage.description.startswith(emoji_markup("wrong")))
                self.assertTrue(permission.description.startswith(emoji_markup("error")))
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
                self.assertIn("Are you sure you want", embed.description)
                self.assertTrue(embed.description.startswith(emoji_markup("warning")))

    def test_requested_examples_match_the_spec(self) -> None:
        ban = success_embed("ban")
        timeout = success_embed("timeout")
        kick = success_embed("kick")
        purge = success_embed("purge")
        self.assertIsNone(ban.title)
        self.assertIn("Banned", ban.description)
        self.assertIn("Reason: Breaking rules", ban.description)
        self.assertIn("Duration: 10 minutes", timeout.description)
        self.assertIn("Reason: Spamming", timeout.description)
        self.assertIn("Kicked", kick.description)
        self.assertIn("Deleted **50 messages**", purge.description)

    def test_ban_and_unban_success_embeds_use_the_real_target_and_reason(self) -> None:
        target = SimpleNamespace(id=123, mention="<@123>")
        ban = success_embed("ban", target=target, reason="Reviewed")
        unban = success_embed("unban", target=target, reason="Appeal accepted")
        self.assertIn("**<@123>**", ban.description)
        self.assertIn("Reason: Reviewed", ban.description)
        self.assertIn("**<@123>**", unban.description)
        self.assertIn("Reason: Appeal accepted", unban.description)

    def test_tempban_embed_uses_the_parsed_duration(self) -> None:
        target = SimpleNamespace(id=123, mention="<@123>")
        embed = success_embed("tempban", target=target, reason="Spamming", duration="2 hours")
        self.assertIn("**<@123>**", embed.description)
        self.assertIn("Duration: 2 hours", embed.description)
        self.assertIn("Reason: Spamming", embed.description)

    def test_timeout_embed_uses_the_actual_duration(self) -> None:
        target = SimpleNamespace(id=123, mention="<@123>")
        embed = success_embed("timeout", target=target, reason="Spamming", duration="20 minutes")
        self.assertIn("**<@123>**", embed.description)
        self.assertIn("Duration: 20 minutes", embed.description)
        self.assertIn("Reason: Spamming", embed.description)

    def test_voice_success_embeds_use_the_shared_success_icon(self) -> None:
        for name in ("voicemute", "voiceunmute", "deafen", "undeafen", "disconnect", "move"):
            with self.subTest(command=name):
                self.assertEqual(success_embed(name).description.count(emoji_markup("success")), 1)

    def test_massban_preview_uses_actual_target_count(self) -> None:
        confirmation = confirmation_embed("massban", count=3)
        success = success_embed("massban", count=2, total=3)
        self.assertIn("You are about to ban 3 members.", confirmation.description)
        self.assertIn("Banned 2 of 3 members", success.description)

    def test_masskick_preview_uses_actual_target_count(self) -> None:
        confirmation = confirmation_embed("masskick", count=4)
        success = success_embed("masskick", count=3, total=4)
        self.assertIn("You are about to kick 4 members.", confirmation.description)
        self.assertIn("Kicked 3 of 4 members", success.description)

    def test_warning_embeds_show_actual_ids_counts_and_paginated_history(self) -> None:
        target = SimpleNamespace(id=123, mention="<@123>")
        warned = success_embed(
            "warn", target=target, reason="@everyone repeated spam", warning_id=44
        )
        self.assertIn("Warning: #44", warned.description)
        self.assertNotIn("@everyone", warned.description)

        removed = success_embed("unwarn", target=target, warning_id=44)
        self.assertIn("Warning removed: #44", removed.description)
        cleared = success_embed("clearwarnings", target=target, count=3)
        self.assertIn("Warnings removed: 3", cleared.description)
        confirmation = confirmation_embed(
            "clearwarnings", count=3, target=target
        )
        self.assertIn("3 warning(s)", confirmation.description)
        self.assertIn("<@123>", confirmation.description)

        warnings = [
            ModerationWarning(
                warning_id=warning_id,
                guild_id=1,
                target_id=123,
                moderator_id=50 + warning_id,
                reason="@here reason",
                created_at="2026-01-01T00:00:00+00:00",
            )
            for warning_id in range(9, 0, -1)
        ]
        pages = warning_history_embeds(target, warnings)
        self.assertEqual(len(pages), 2)
        self.assertIn("Active warnings: 9", pages[0].description)
        self.assertEqual(len(pages[0].fields), 8)
        self.assertEqual(len(pages[1].fields), 1)
        self.assertIn("Warning #9", pages[0].fields[0].name)
        self.assertNotIn("@here", pages[0].fields[0].value)

    def test_warnlist_warnstats_and_purge_embeds_use_actual_results(self) -> None:
        target = SimpleNamespace(id=123, mention="<@123>")
        warning = ModerationWarning(
            warning_id=104,
            guild_id=1,
            target_id=123,
            moderator_id=50,
            reason="@everyone repeated spam",
            created_at="2026-01-01T00:00:00+00:00",
        )
        warning_page = warning_list_embed(
            [warning], total=9, page=2, page_size=8, target=target
        )
        self.assertIn("Warning list for **<@123>**", warning_page.title)
        self.assertIn("Page: 2 of 2", warning_page.description)
        self.assertIn("<@50>", warning_page.fields[0].value)
        self.assertNotIn("@everyone", warning_page.fields[0].value)

        stats = warning_stats_embed(
            WarningStats(
                total_warnings=12,
                members_warned=8,
                moderators_with_warnings=3,
            )
        )
        self.assertIn("Total warnings: 12", stats.description)
        self.assertIn("Members warned: 8", stats.description)
        self.assertIn("Moderators with warnings: 3", stats.description)

        self.assertEqual(
            success_embed("purge", count=7).description,
            f"{emoji_markup('success')} Deleted **7 messages**",
        )
        self.assertIn("**<@123>**", success_embed("purgeuser", count=5, target=target).description)
        self.assertIn("Deleted **2 bot messages**", success_embed("purgebots", count=2).description)
        self.assertIn("Deleted **3 human messages**", success_embed("purgehumans", count=3).description)
        self.assertIn("Deleted **4 messages** containing links", success_embed("purgelinks", count=4).description)
        self.assertIn(
            "5 messages from **<@123>**",
            confirmation_embed("purgeuser", count=5, target=target).description,
        )
        self.assertIn(
            "4 messages containing links",
            confirmation_embed("purgelinks", count=4).description,
        )

    def test_custom_emoji_catalog_and_unknown_handling(self) -> None:
        self.assertEqual(len(EMOJI_IDS), 40)
        self.assertEqual(emoji_markup("success"), "<:success:1518658821650776225>")
        self.assertEqual(emoji_for("success"), emoji_markup("success"))
        self.assertEqual(emoji_for("success", object()), emoji_markup("success"))
        self.assertEqual(emoji_for("information"), "")
        self.assertEqual(emoji_markup("not-a-configured-emoji"), "")
        self.assertFalse(hasattr(emoji_manager_module, "UNICODE_FALLBACKS"))


if __name__ == "__main__":
    unittest.main()
