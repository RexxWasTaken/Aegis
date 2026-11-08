from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from core.emoji_manager import emoji_markup
from core.giveaway_manager import (
    GIVEAWAY_EMOJI_ID,
    GiveawayManager,
    IncompleteParticipantList,
)
from database.repositories.community import GiveawayRecord
from embeds.giveaway import giveaway_announcement, giveaway_ended_embed
from embeds.help import help_front_page
from embeds.ticket import ticket_panel_embed


class CommunityUiTests(unittest.IsolatedAsyncioTestCase):
    def test_help_home_and_ticket_panel_use_required_custom_emojis(self) -> None:
        help_embed = help_front_page(["Moderation", "Ticket", "Giveaway"])
        self.assertEqual(help_embed.title, "Welcome to AEGIS!")
        self.assertEqual(
            help_embed.description,
            "Your ultimate versatile Discord bot.\n"
            "Use the dropdown menus below to explore command categories.",
        )
        category_list = help_embed.fields[0].value
        self.assertEqual(
            category_list.splitlines(),
            [
                f"{emoji_markup('moderation')} Moderation",
                f"{emoji_markup('ticket')} Ticket",
                f"{emoji_markup('giveaway')} Giveaway",
            ],
        )

        panel = ticket_panel_embed()
        self.assertIsNone(panel.title)
        self.assertEqual(
            panel.description,
            "Make Ticket For Complains Here\n\n"
            "To create a ticket, select an issue from the dropdown below.\n\n"
            f"{emoji_markup('ticket')} AEGIS Support",
        )

    def test_giveaway_embed_uses_custom_reaction_and_never_unicode_confetti(self) -> None:
        host = SimpleNamespace(id=10, mention="<@10>")
        ends_at = datetime.now(timezone.utc) + timedelta(hours=1)
        announcement = giveaway_announcement(
            prize="Test prize",
            winner_count=2,
            host=host,
            ends_at=ends_at,
        )
        self.assertIn("<:giveaway:1518667382581760110> NEW GIVEAWAY", announcement.title)
        self.assertIn(
            f"React with {emoji_markup('giveaway')} to enter!",
            announcement.description,
        )
        self.assertNotIn("🎉", announcement.title + announcement.description)

        record = GiveawayRecord(
            message_id=50,
            guild_id=1,
            channel_id=2,
            host_id=10,
            prize="Test prize",
            winner_count=2,
            ends_at=ends_at.isoformat(),
            status="ended",
            paused_seconds=None,
            winners=(20, 21),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        ended = giveaway_ended_embed(record, winners=(20, 21))
        self.assertIn("<:giveaway:1518667382581760110> GIVEAWAY ENDED", ended.title)
        self.assertIn(f"{emoji_markup('success')} <@20>", ended.description)
        self.assertNotIn("🎉", ended.title + ended.description)

    async def test_participants_are_fetched_from_the_exact_current_reaction(self) -> None:
        host_id, bot_id, entrant_id = 10, 99, 20
        reaction = SimpleNamespace(
            emoji=discord.PartialEmoji.from_str(emoji_markup("giveaway"))
        )

        async def users(*, limit: int | None = None):
            self.assertIsNone(limit)
            for user_id in (host_id, bot_id, entrant_id, entrant_id):
                yield SimpleNamespace(id=user_id)

        reaction.users = users
        message = SimpleNamespace(reactions=[reaction])
        channel = Mock(spec=discord.TextChannel)
        channel.fetch_message = AsyncMock(return_value=message)
        bot = SimpleNamespace(
            user=SimpleNamespace(id=bot_id),
            get_channel=lambda channel_id: channel,
        )
        manager = GiveawayManager(bot, Mock())
        record = GiveawayRecord(
            message_id=50,
            guild_id=1,
            channel_id=2,
            host_id=host_id,
            prize="Test prize",
            winner_count=1,
            ends_at=datetime.now(timezone.utc).isoformat(),
            status="active",
            paused_seconds=None,
            winners=(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        returned_channel, participants = await manager._participants(record)
        self.assertIs(returned_channel, channel)
        self.assertEqual(participants, [entrant_id])
        self.assertEqual(GIVEAWAY_EMOJI_ID, 1518667382581760110)

    async def test_missing_custom_reaction_prevents_winner_selection(self) -> None:
        message = SimpleNamespace(reactions=[])
        channel = Mock(spec=discord.TextChannel)
        channel.fetch_message = AsyncMock(return_value=message)
        manager = GiveawayManager(
            SimpleNamespace(
                user=SimpleNamespace(id=99),
                get_channel=lambda channel_id: channel,
            ),
            Mock(),
        )
        record = GiveawayRecord(
            message_id=50,
            guild_id=1,
            channel_id=2,
            host_id=10,
            prize="Test prize",
            winner_count=1,
            ends_at=datetime.now(timezone.utc).isoformat(),
            status="active",
            paused_seconds=None,
            winners=(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self.assertRaises(IncompleteParticipantList):
            await manager._participants(record)


if __name__ == "__main__":
    unittest.main()
