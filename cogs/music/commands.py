"""Hybrid prefix/slash commands for the AEGIS music player."""

from __future__ import annotations

import asyncio
import logging
import weakref

import discord
import wavelink
from discord import app_commands
from discord.ext import commands

from cogs.music.controls import QueuePaginationView
from cogs.music.player import AegisPlayer, MusicPlayerEvents
from cogs.music.queue import (
    build_queue_page,
    play_previous,
    set_repeat_mode,
    shuffle_queue,
)
from core.emoji_manager import emoji_markup
from core.music_manager import MusicServiceUnavailable, get_music_manager
from embeds.music import lyrics_embed, player_embed, queue_embed
from utils.music_helpers import fetch_lyrics, parse_seek_position


logger = logging.getLogger(__name__)
MAX_QUEUE_SIZE = 5000

COMMAND_EMOJIS = {
    "play": "play",
    "pause": "pause",
    "resume": "play",
    "skip": "next",
    "stop": "stop",
    "queue": "queue",
    "nowplaying": "media",
    "volume": "volume",
    "loop": "repeat",
    "shuffle": "shuffle",
    "lyrics": "media",
    "seek": "media",
    "remove": "delete",
    "clear": "delete",
    "join": "voice",
    "leave": "voice",
    "previous": "previous",
    "autoplay": "favorite",
}


class MusicCog(commands.Cog):
    """Music commands backed exclusively by Wavelink and Lavalink."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._connection_locks: weakref.WeakValueDictionary[int, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    async def cog_load(self) -> None:
        """Attach the exact existing custom emoji to Help metadata."""
        for command in self.get_commands():
            emoji_name = COMMAND_EMOJIS.get(command.name)
            if emoji_name is None:
                continue
            command.extras["help_emoji"] = emoji_name
            app_command = getattr(command, "app_command", None)
            if app_command is not None:
                app_command.extras["help_emoji"] = emoji_name

    def _connection_lock(self, guild_id: int) -> asyncio.Lock:
        """Share a short-lived lock while any command is creating a guild player."""
        lock = self._connection_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._connection_locks[guild_id] = lock
        return lock

    @staticmethod
    def _send_options(ctx: commands.Context) -> dict[str, object]:
        options: dict[str, object] = {
            "allowed_mentions": discord.AllowedMentions.none(),
        }
        if ctx.interaction is not None:
            options["ephemeral"] = True
        return options

    async def _reply(self, ctx: commands.Context, content: str, **kwargs: object) -> None:
        options = self._send_options(ctx)
        options.update(kwargs)
        await ctx.send(content, **options)

    async def _error(self, ctx: commands.Context, message: str) -> None:
        await self._reply(ctx, f"{emoji_markup('error')} {message}")

    @staticmethod
    def _voice_channel(ctx: commands.Context) -> discord.VoiceChannel | discord.StageChannel | None:
        voice_state = getattr(ctx.author, "voice", None)
        channel = getattr(voice_state, "channel", None)
        if isinstance(channel, (discord.VoiceChannel, discord.StageChannel)):
            return channel
        return None

    async def _get_player(
        self,
        ctx: commands.Context,
        *,
        connect: bool = False,
        allow_move_when_idle: bool = False,
    ) -> AegisPlayer | None:
        guild = ctx.guild
        if guild is None:
            await self._error(ctx, "Music commands are only available in a server.")
            return None

        async with self._connection_lock(guild.id):
            return await self._get_player_locked(
                ctx,
                connect=connect,
                allow_move_when_idle=allow_move_when_idle,
            )

    async def _get_player_locked(
        self,
        ctx: commands.Context,
        *,
        connect: bool,
        allow_move_when_idle: bool,
    ) -> AegisPlayer | None:
        guild = ctx.guild
        assert guild is not None
        voice_channel = self._voice_channel(ctx)
        if voice_channel is None:
            await self._error(ctx, "Join a voice channel first.")
            return None

        try:
            get_music_manager(self.bot)
        except MusicServiceUnavailable as exc:
            await self._error(ctx, f"Music is unavailable. {exc}")
            return None

        current = guild.voice_client
        if current is not None and not isinstance(current, AegisPlayer):
            await self._error(
                ctx,
                "This server's voice connection is owned by another voice client.",
            )
            return None

        if isinstance(current, AegisPlayer):
            if current.guild is None or current.guild.id != guild.id:
                await self._error(ctx, "That player does not belong to this server.")
                return None
            if current.channel.id != voice_channel.id:
                if (
                    allow_move_when_idle
                    and current.current is None
                    and not current.queue
                ):
                    permissions = voice_channel.permissions_for(guild.me)
                    if not permissions.view_channel or not permissions.connect or not permissions.speak:
                        await self._error(
                            ctx,
                            "I need View Channel, Connect, and Speak permissions in that voice channel.",
                        )
                        return None
                    try:
                        await current.move_to(voice_channel)
                    except (discord.Forbidden, discord.HTTPException, wavelink.LavalinkException):
                        await self._error(ctx, "I could not move to that voice channel.")
                        return None
                else:
                    await self._error(
                        ctx,
                        "Join the same voice channel as the active music player.",
                    )
                    return None
            if current.home_channel is None:
                current.home_channel = ctx.channel
            return current

        if not connect:
            await self._error(ctx, "There is no music player in this server yet.")
            return None

        permissions = voice_channel.permissions_for(guild.me)
        if not permissions.view_channel or not permissions.connect or not permissions.speak:
            await self._error(
                ctx,
                "I need View Channel, Connect, and Speak permissions in that voice channel.",
            )
            return None

        try:
            player = await voice_channel.connect(cls=AegisPlayer)
        except (discord.Forbidden, discord.HTTPException, discord.ClientException) as exc:
            logger.warning("Could not connect to voice in guild %s: %s", guild.id, exc)
            await self._error(ctx, "I could not join that voice channel.")
            return None

        player.home_channel = ctx.channel
        player.autoplay = wavelink.AutoPlayMode.disabled
        return player

    @staticmethod
    def _search_options(query: str) -> tuple[str, wavelink.TrackSource]:
        """Use YouTube by default and accept an explicit SoundCloud search prefix."""
        normalized = query.strip()
        lowered = normalized.casefold()
        if lowered.startswith("scsearch:"):
            return normalized[len("scsearch:") :].strip(), wavelink.TrackSource.SoundCloud
        if lowered.startswith("sc:"):
            return normalized[3:].strip(), wavelink.TrackSource.SoundCloud
        return normalized, wavelink.TrackSource.YouTube

    @commands.hybrid_command(
        name="play",
        aliases=["p"],
        description="Play a YouTube search, supported URL, or playlist.",
    )
    @app_commands.describe(query="A song search, YouTube/SoundCloud URL, or supported playlist URL.")
    async def play(self, ctx: commands.Context, *, query: str) -> None:
        """Search or load a supported URL and add its tracks to this server's queue."""
        player = await self._get_player(ctx, connect=True)
        if player is None:
            return

        query, source = self._search_options(query)
        if not query:
            await self._error(ctx, "Enter a search phrase or supported music URL.")
            return

        try:
            results = await wavelink.Playable.search(query, source=source)
        except (wavelink.LavalinkException, wavelink.LavalinkLoadException, wavelink.NodeException) as exc:
            logger.warning("Music search failed in guild %s: %s", ctx.guild.id, exc)
            await self._error(ctx, "Lavalink could not load that search or URL.")
            return

        if not results:
            await self._error(ctx, "No playable tracks were found for that search or URL.")
            return

        playlist_name = results.name if isinstance(results, wavelink.Playlist) else None
        requested_tracks = list(results) if isinstance(results, wavelink.Playlist) else [results[0]]
        remaining = max(0, MAX_QUEUE_SIZE - len(player.queue))
        requested_tracks = requested_tracks[:remaining]
        if not requested_tracks:
            await self._error(ctx, "This server's queue is full.")
            return

        for track in requested_tracks:
            track.extras = {
                **dict(track.extras),
                "requester_id": ctx.author.id,
                "requester_name": str(ctx.author),
            }

        try:
            added = await player.queue.put_wait(requested_tracks)
            if player.current is None and player.queue:
                await player.play(player.queue.get(), volume=70)
        except (wavelink.LavalinkException, wavelink.NodeException, discord.HTTPException) as exc:
            logger.warning("Playback could not start in guild %s: %s", ctx.guild.id, exc)
            await self._error(ctx, "The track could not start. Try another result or URL.")
            return

        await player.update_panel()
        if playlist_name:
            message = f"{emoji_markup('queue')} Added {added} track(s) from **{playlist_name[:100]}**."
        elif "open.spotify.com" in query.casefold():
            message = (
                f"{emoji_markup('play')} Added a playable match for the Spotify item. "
                "Spotify metadata is resolved to audio from a supported Lavalink source."
            )
        else:
            title = requested_tracks[0].title[:150]
            message = f"{emoji_markup('play')} Added **{title}** to the queue."
        await self._reply(ctx, message)

    @commands.hybrid_command(
        name="pause",
        aliases=["pa"],
        description="Pause the current track.",
    )
    async def pause(self, ctx: commands.Context) -> None:
        """Pause the active track for this server."""
        player = await self._get_player(ctx)
        if player is None:
            return
        if player.current is None:
            await self._error(ctx, "Nothing is playing.")
            return
        await player.pause(True)
        await player.update_panel()
        await self._reply(ctx, f"{emoji_markup('pause')} Playback paused.")

    @commands.hybrid_command(
        name="resume",
        aliases=["r"],
        description="Resume the current track.",
    )
    async def resume(self, ctx: commands.Context) -> None:
        """Resume a paused track for this server."""
        player = await self._get_player(ctx)
        if player is None:
            return
        if player.current is None:
            await self._error(ctx, "Nothing is playing.")
            return
        await player.pause(False)
        await player.update_panel()
        await self._reply(ctx, f"{emoji_markup('play')} Playback resumed.")

    @commands.hybrid_command(
        name="skip",
        aliases=["s"],
        description="Skip the current track.",
    )
    async def skip(self, ctx: commands.Context) -> None:
        """Skip the current track and continue with the queue."""
        player = await self._get_player(ctx)
        if player is None:
            return
        if player.current is None:
            await self._error(ctx, "Nothing is playing.")
            return
        await player.skip(force=True)
        await player.update_panel()
        await self._reply(ctx, f"{emoji_markup('next')} Skipped the current track.")

    @commands.hybrid_command(
        name="stop",
        aliases=["st"],
        description="Stop playback, clear the queue, and disable autoplay.",
    )
    async def stop(self, ctx: commands.Context) -> None:
        """Stop the player and discard upcoming and autoplay tracks."""
        player = await self._get_player(ctx)
        if player is None:
            return
        player.queue.clear()
        player.auto_queue.clear()
        player.autoplay = wavelink.AutoPlayMode.disabled
        if player.current is not None:
            await player.skip(force=True)
        await player.update_panel()
        await self._reply(ctx, f"{emoji_markup('stop')} Playback stopped and the queue was cleared.")

    @commands.hybrid_command(
        name="queue",
        aliases=["q"],
        description="Show upcoming tracks with page controls.",
    )
    @app_commands.describe(page="The queue page to show.")
    async def queue(self, ctx: commands.Context, page: int = 1) -> None:
        """Show a paginated queue for this server."""
        player = await self._get_player(ctx)
        if player is None:
            return
        page_data = build_queue_page(player.queue, page)
        view = QueuePaginationView(
            player,
            page=page_data.page,
            page_count=page_data.page_count,
        )
        message = await ctx.send(
            embed=queue_embed(
                page_data.tracks,
                page=page_data.page,
                page_count=page_data.page_count,
                total=page_data.total,
            ),
            view=view,
            **self._send_options(ctx),
        )
        if isinstance(message, discord.Message):
            view.message = message

    @commands.hybrid_command(
        name="nowplaying",
        aliases=["np", "now"],
        description="Show the current track and player controls.",
    )
    async def nowplaying(self, ctx: commands.Context) -> None:
        """Show the current player card."""
        player = await self._get_player(ctx)
        if player is None:
            return
        if player.current is None:
            await self._error(ctx, "Nothing is playing.")
            return
        await ctx.send(
            embed=player_embed(player),
            **self._send_options(ctx),
        )

    @commands.hybrid_command(
        name="volume",
        aliases=["vol", "v"],
        description="Show or set player volume from 0 to 200 percent.",
    )
    @app_commands.describe(level="A volume from 0 to 200. Omit to show the current level.")
    async def volume(self, ctx: commands.Context, level: int | None = None) -> None:
        """Set the per-server player volume."""
        player = await self._get_player(ctx)
        if player is None:
            return
        if level is None:
            await self._reply(ctx, f"{emoji_markup('volume')} Volume is {player.volume}%.")
            return
        if not 0 <= level <= 200:
            await self._error(ctx, "Volume must be between 0 and 200.")
            return
        await player.set_volume(level)
        await self._reply(ctx, f"{emoji_markup('volume')} Volume set to {level}%.")

    @commands.hybrid_command(
        name="loop",
        aliases=["lp"],
        description="Set repeat mode to off, track, or queue.",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Off", value="off"),
            app_commands.Choice(name="Track", value="track"),
            app_commands.Choice(name="Queue", value="queue"),
        ]
    )
    async def loop(self, ctx: commands.Context, mode: str = "off") -> None:
        """Set the queue's repeat mode."""
        player = await self._get_player(ctx)
        if player is None:
            return
        try:
            selected = set_repeat_mode(player, mode)
        except ValueError as exc:
            await self._error(ctx, str(exc))
            return
        await player.update_panel()
        await self._reply(ctx, f"{emoji_markup('repeat')} Repeat mode: **{selected}**.")

    @commands.hybrid_command(
        name="shuffle",
        aliases=["sh"],
        description="Shuffle upcoming tracks.",
    )
    async def shuffle(self, ctx: commands.Context) -> None:
        """Shuffle only the upcoming tracks for this server."""
        player = await self._get_player(ctx)
        if player is None:
            return
        count = shuffle_queue(player)
        if count < 2:
            await self._error(ctx, "Add at least two upcoming tracks before shuffling.")
            return
        await self._reply(ctx, f"{emoji_markup('shuffle')} Shuffled {count} upcoming track(s).")

    @commands.hybrid_command(
        name="lyrics",
        aliases=["ly"],
        description="Look up lyrics for the current track.",
    )
    async def lyrics(self, ctx: commands.Context) -> None:
        """Look up current-track lyrics through LRCLIB."""
        player = await self._get_player(ctx)
        if player is None:
            return
        track = player.current
        if track is None:
            await self._error(ctx, "Start a track before requesting lyrics.")
            return
        lyrics = await fetch_lyrics(track)
        if not lyrics:
            await self._error(ctx, "No lyrics were found for the current track.")
            return
        await ctx.send(
            embed=lyrics_embed(track, lyrics),
            **self._send_options(ctx),
        )

    @commands.hybrid_command(
        name="seek",
        description="Seek to a time in the current track.",
    )
    @app_commands.describe(position="Time in seconds, MM:SS, or HH:MM:SS.")
    async def seek(self, ctx: commands.Context, position: str) -> None:
        """Seek within the current seekable track."""
        player = await self._get_player(ctx)
        if player is None:
            return
        track = player.current
        if track is None:
            await self._error(ctx, "Nothing is playing.")
            return
        if track.is_stream or not track.is_seekable:
            await self._error(ctx, "The current track cannot be seeked.")
            return
        try:
            target = parse_seek_position(position, duration_ms=track.length)
        except ValueError as exc:
            await self._error(ctx, str(exc))
            return
        await player.seek(target)
        await player.update_panel()
        await self._reply(ctx, f"{emoji_markup('media')} Seeked to `{position}`.")

    @commands.hybrid_command(
        name="remove",
        description="Remove an upcoming track by its queue position.",
    )
    @app_commands.describe(position="The 1-based position in the upcoming queue.")
    async def remove(self, ctx: commands.Context, position: int) -> None:
        """Remove one upcoming queue entry."""
        player = await self._get_player(ctx)
        if player is None:
            return
        if position < 1 or position > len(player.queue):
            await self._error(ctx, "That queue position does not exist.")
            return
        track = player.queue[position - 1]
        player.queue.delete(position - 1)
        await self._reply(ctx, f"{emoji_markup('delete')} Removed **{track.title[:150]}**.")

    @commands.hybrid_command(
        name="clear",
        description="Clear upcoming tracks without stopping the current track.",
    )
    async def clear(self, ctx: commands.Context) -> None:
        """Clear only upcoming tracks; leave the current track untouched."""
        player = await self._get_player(ctx)
        if player is None:
            return
        count = len(player.queue)
        player.queue.clear()
        player.auto_queue.clear()
        await player.update_panel()
        await self._reply(ctx, f"{emoji_markup('delete')} Cleared {count} upcoming track(s).")

    @commands.hybrid_command(
        name="join",
        aliases=["j"],
        description="Join your voice channel.",
    )
    async def join(self, ctx: commands.Context) -> None:
        """Join the caller's voice channel, moving only while the player is idle."""
        player = await self._get_player(ctx, connect=True, allow_move_when_idle=True)
        if player is not None:
            await self._reply(ctx, f"{emoji_markup('voice')} Joined {player.channel.mention}.")

    @commands.hybrid_command(
        name="leave",
        aliases=["dc"],
        description="Disconnect the music player from voice.",
    )
    async def leave(self, ctx: commands.Context) -> None:
        """Stop and disconnect the player for this server."""
        player = await self._get_player(ctx)
        if player is None:
            return
        await player.close_panel("The player was disconnected.")
        await player.disconnect()
        await self._reply(ctx, f"{emoji_markup('voice')} Left the voice channel.")

    @commands.hybrid_command(
        name="previous",
        description="Play the previous track from this session.",
    )
    async def previous(self, ctx: commands.Context) -> None:
        """Return to the prior track while keeping the current track queued."""
        player = await self._get_player(ctx)
        if player is None:
            return
        track = await play_previous(player)
        if track is None:
            await self._error(ctx, "There is no previous track in this session.")
            return
        await player.update_panel()
        await self._reply(ctx, f"{emoji_markup('previous')} Playing **{track.title[:150]}**.")

    @commands.hybrid_command(
        name="autoplay",
        description="Enable or disable Wavelink autoplay recommendations.",
    )
    @app_commands.describe(enabled="Whether to enable autoplay.")
    async def autoplay(self, ctx: commands.Context, enabled: bool | None = None) -> None:
        """Toggle or explicitly set Wavelink autoplay."""
        player = await self._get_player(ctx)
        if player is None:
            return
        if enabled is None:
            enabled = player.autoplay is not wavelink.AutoPlayMode.enabled
        player.autoplay = (
            wavelink.AutoPlayMode.enabled if enabled else wavelink.AutoPlayMode.disabled
        )
        await player.update_panel()
        label = "enabled" if enabled else "disabled"
        await self._reply(ctx, f"{emoji_markup('favorite')} Autoplay {label}.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MusicPlayerEvents(bot))
    await bot.add_cog(MusicCog(bot))
