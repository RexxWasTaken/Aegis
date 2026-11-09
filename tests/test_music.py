from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord
import wavelink
from discord.ext import commands

from cogs.music.commands import COMMAND_EMOJIS, MusicCog
from cogs.music.controls import PlayerControls, authorize_player_interaction
from cogs.music.queue import (
    build_queue_page,
    play_previous,
    set_repeat_mode,
    shuffle_queue,
)
from core.emoji_manager import EMOJI_IDS, emoji_markup
from core.music_manager import MusicManager
from embeds.music import player_embed, queue_embed
from embeds.music import lyrics_embed
from utils.music_helpers import (
    fetch_lyrics,
    format_duration,
    parse_seek_position,
    progress_bar,
)


def _track(identifier: str, *, title: str | None = None) -> wavelink.Playable:
    return wavelink.Playable(
        {
            "encoded": f"encoded-{identifier}",
            "info": {
                "identifier": identifier,
                "isSeekable": True,
                "author": "Test Artist",
                "length": 125_000,
                "isStream": False,
                "position": 0,
                "title": title or f"Track {identifier}",
                "sourceName": "youtube",
            },
            "pluginInfo": {},
            "userData": {},
        }
    )


class MusicHelperTests(unittest.TestCase):
    def test_duration_and_progress_formatting(self) -> None:
        self.assertEqual(format_duration(125_000), "2:05")
        self.assertEqual(format_duration(3_723_000), "1:02:03")
        self.assertEqual(progress_bar(5_000, 10_000, width=10), "[#####-----]")
        self.assertEqual(progress_bar(0, 0), "[----------------]")

    def test_seek_parser_accepts_seconds_and_clock_formats(self) -> None:
        self.assertEqual(parse_seek_position("92"), 92_000)
        self.assertEqual(parse_seek_position("2:05"), 125_000)
        self.assertEqual(parse_seek_position("1:02:03"), 3_723_000)
        with self.assertRaises(ValueError):
            parse_seek_position("-3")
        with self.assertRaises(ValueError):
            parse_seek_position("1:02", duration_ms=62_000)
        with self.assertRaises(ValueError):
            parse_seek_position("1:75")

    def test_requester_and_music_emoji_mappings_are_existing_catalog_entries(self) -> None:
        for emoji_name in COMMAND_EMOJIS.values():
            self.assertIn(emoji_name, EMOJI_IDS)
            self.assertEqual(
                emoji_markup(emoji_name),
                f"<:{emoji_name}:{EMOJI_IDS[emoji_name]}>",
            )


class MusicQueueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.queue = wavelink.Queue()
        for index in range(12):
            self.queue.put(_track(str(index)))
        self.player = SimpleNamespace(
            queue=self.queue,
            current=_track("current"),
            play=AsyncMock(),
        )

    def test_queue_pages_clamp_and_show_expected_tracks(self) -> None:
        first = build_queue_page(self.queue, 1)
        last = build_queue_page(self.queue, 99)
        self.assertEqual((first.page, first.page_count, first.total), (1, 2, 12))
        self.assertEqual(len(first.tracks), 10)
        self.assertEqual((last.page, len(last.tracks)), (2, 2))
        embed = queue_embed(
            first.tracks,
            page=first.page,
            page_count=first.page_count,
            total=first.total,
        )
        self.assertIn("Track 0", embed.description)
        self.assertIn("Page 1 of 2", embed.footer.text)

    def test_loop_modes_and_shuffle_only_touch_upcoming_queue(self) -> None:
        self.assertEqual(set_repeat_mode(self.player, "track"), "track")
        self.assertIs(self.queue.mode, wavelink.QueueMode.loop)
        self.assertEqual(set_repeat_mode(self.player, "queue"), "queue")
        self.assertIs(self.queue.mode, wavelink.QueueMode.loop_all)
        self.assertEqual(set_repeat_mode(self.player, "off"), "off")
        self.assertIs(self.queue.mode, wavelink.QueueMode.normal)
        with self.assertRaises(ValueError):
            set_repeat_mode(self.player, "invalid")
        self.assertEqual(shuffle_queue(self.player), 12)
        self.assertEqual(len(self.queue), 12)
        self.assertEqual(self.player.current.title, "Track current")

    async def test_previous_requeues_current_and_plays_prior_history_entry(self) -> None:
        history = self.queue.history
        assert history is not None
        previous = _track("previous")
        history.put(previous)
        history.put(_track("current-history"))
        result = await play_previous(self.player)
        self.assertEqual(result, previous)
        self.assertEqual(self.queue[0], self.player.current)
        self.player.play.assert_awaited_once_with(previous, add_history=False)


class MusicIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_music_cog_registers_every_prefix_alias_and_slash_command(self) -> None:
        bot = commands.Bot(command_prefix="a!", intents=discord.Intents.none())
        try:
            await bot.add_cog(MusicCog(bot))
            expected = {
                "play": ("p",),
                "pause": ("pa",),
                "resume": ("r",),
                "skip": ("s",),
                "stop": ("st",),
                "queue": ("q",),
                "nowplaying": ("np", "now"),
                "volume": ("vol", "v"),
                "loop": ("lp",),
                "shuffle": ("sh",),
                "lyrics": ("ly",),
                "seek": (),
                "remove": (),
                "clear": (),
                "join": ("j",),
                "leave": ("dc",),
                "previous": (),
                "autoplay": (),
            }
            for name, aliases in expected.items():
                command = bot.get_command(name)
                self.assertIsNotNone(command, name)
                self.assertEqual(tuple(command.aliases), aliases, name)
                for alias in aliases:
                    self.assertIs(bot.get_command(alias), command, alias)
                self.assertIn(name, {item.name for item in bot.tree.get_commands()})
            self.assertEqual(bot.get_command("play").extras["help_emoji"], "play")
        finally:
            await bot.close()

    async def test_manager_reports_missing_password_without_blocking_startup(self) -> None:
        manager = MusicManager(object(), uri="http://127.0.0.1:2333", password="")
        self.assertFalse(await manager.connect())
        self.assertFalse(manager.available)
        with self.assertRaisesRegex(RuntimeError, "LAVALINK_PASSWORD"):
            manager.require_node()

    async def test_player_controls_reject_other_guilds_and_accept_same_voice(self) -> None:
        player_channel = SimpleNamespace(id=12)
        player = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            channel=player_channel,
        )
        response = SimpleNamespace(send_message=AsyncMock())
        wrong_guild = SimpleNamespace(
            guild_id=2,
            user=SimpleNamespace(voice=SimpleNamespace(channel=player_channel)),
            response=response,
        )
        self.assertFalse(await authorize_player_interaction(wrong_guild, player))
        response.send_message.assert_awaited_once()

        right_guild = SimpleNamespace(
            guild_id=1,
            user=SimpleNamespace(voice=SimpleNamespace(channel=player_channel)),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        self.assertTrue(await authorize_player_interaction(right_guild, player))
        right_guild.response.send_message.assert_not_awaited()

    async def test_player_embed_shows_artists_progress_requester_and_loop_state(self) -> None:
        track = _track("panel", title="Panel Song")
        track.extras = {"requester_id": 42}
        queue = wavelink.Queue()
        queue.mode = wavelink.QueueMode.loop
        player = SimpleNamespace(
            current=track,
            position=60_000,
            queue=queue,
            autoplay=wavelink.AutoPlayMode.disabled,
        )
        embed = player_embed(player)
        self.assertEqual(embed.title, "Panel Song")
        self.assertIn("Test Artist", embed.description)
        fields = {field.name: field.value for field in embed.fields}
        self.assertIn("######", fields[f"{emoji_markup('media')} Playback"])
        self.assertEqual(fields["Requested by"], "<@42>")
        self.assertIn("Loop: Track", embed.footer.text)
        self.assertIn("Autoplay: Off", embed.footer.text)

    async def test_player_buttons_pause_skip_and_stop_without_cross_server_access(self) -> None:
        player = SimpleNamespace(
            guild=SimpleNamespace(id=1),
            channel=SimpleNamespace(id=12),
            current=_track("button"),
            paused=False,
            queue=wavelink.Queue(),
            auto_queue=wavelink.Queue(),
            autoplay=wavelink.AutoPlayMode.enabled,
            pause=AsyncMock(),
            skip=AsyncMock(),
            update_panel=AsyncMock(),
        )
        player.queue.put(_track("queued"))
        view = PlayerControls(player)
        result = await view.run_action("toggle")
        self.assertEqual(result, "Playback paused.")
        player.pause.assert_awaited_once_with(True)
        await view.run_action("stop")
        self.assertFalse(player.queue)
        self.assertFalse(player.auto_queue)
        self.assertIs(player.autoplay, wavelink.AutoPlayMode.disabled)
        player.skip.assert_awaited_once_with(force=True)

    async def test_lyrics_embed_stays_within_discord_description_limit(self) -> None:
        embed = lyrics_embed(_track("lyrics"), "word\n" * 5000)
        self.assertLessEqual(len(embed.description or ""), 4096)

    async def test_lyrics_lookup_uses_plain_text_or_strips_synced_timestamps(self) -> None:
        track = _track("lyrics", title="Song")

        class FakeResponse:
            status = 200

            def __init__(self, data: dict[str, str]) -> None:
                self.data = data

            async def __aenter__(self) -> FakeResponse:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            def raise_for_status(self) -> None:
                return None

            async def json(self, *, content_type: str | None = None) -> dict[str, str]:
                return self.data

        class FakeSession:
            def __init__(self, data: dict[str, str]) -> None:
                self.data = data

            async def __aenter__(self) -> FakeSession:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            def get(self, *args: object, **kwargs: object) -> FakeResponse:
                return FakeResponse(self.data)

        with patch(
            "utils.music_helpers.aiohttp.ClientSession",
            return_value=FakeSession({"syncedLyrics": "[00:01.10]First line\n[00:02.00]Second line"}),
        ):
            self.assertEqual(await fetch_lyrics(track), "First line\nSecond line")

        with patch(
            "utils.music_helpers.aiohttp.ClientSession",
            return_value=FakeSession({"plainLyrics": "Plain words"}),
        ):
            self.assertEqual(await fetch_lyrics(track), "Plain words")


if __name__ == "__main__":
    unittest.main()
