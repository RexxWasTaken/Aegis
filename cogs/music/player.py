"""Wavelink player subclass, live panel updates, and playback event listeners."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
import wavelink
from discord.ext import commands, tasks

from cogs.music.controls import PlayerControls
from core.emoji_manager import emoji_markup
from embeds.music import player_embed


logger = logging.getLogger(__name__)


class AegisPlayer(wavelink.Player):
    """A single guild's Wavelink session and its text-channel player panel."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.home_channel: discord.abc.Messageable | None = None
        self.panel_message: discord.Message | None = None
        self.panel_view: PlayerControls | None = None
        self._panel_lock = asyncio.Lock()

    async def update_panel(self) -> None:
        """Create or edit the player card, recovering cleanly if it was deleted."""
        if self.home_channel is None:
            return

        async with self._panel_lock:
            embed = player_embed(self)
            if self.current is None:
                if self.panel_view is not None:
                    self.panel_view.stop()
                    self.panel_view = None
                if self.panel_message is not None:
                    try:
                        await self.panel_message.edit(
                            embed=embed,
                            view=None,
                            allowed_mentions=discord.AllowedMentions.none(),
                        )
                    except discord.NotFound:
                        self.panel_message = None
                    except discord.HTTPException:
                        logger.debug("Could not clear an inactive player panel.", exc_info=True)
                return

            if self.panel_view is None or self.panel_view.is_finished():
                self.panel_view = PlayerControls(self)
            else:
                self.panel_view.refresh_state()

            try:
                if self.panel_message is None:
                    self.panel_message = await self.home_channel.send(
                        embed=embed,
                        view=self.panel_view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                else:
                    await self.panel_message.edit(
                        embed=embed,
                        view=self.panel_view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
            except discord.NotFound:
                self.panel_message = None
                try:
                    self.panel_message = await self.home_channel.send(
                        embed=embed,
                        view=self.panel_view,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    logger.warning("Could not recreate a deleted music panel.", exc_info=True)
            except discord.HTTPException:
                logger.warning("Could not update the music panel.", exc_info=True)

    async def close_panel(self, message: str = "Playback has ended.") -> None:
        """Remove controls and leave a short status when the session disconnects."""
        if self.panel_view is not None:
            self.panel_view.stop()
            self.panel_view = None
        if self.panel_message is None:
            return
        embed = discord.Embed(
            title=f"{emoji_markup('music')} AEGIS Music",
            description=message,
            color=discord.Color(0x12A8FF),
        )
        try:
            await self.panel_message.edit(
                embed=embed,
                view=None,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.NotFound:
            pass
        except discord.HTTPException:
            logger.debug("Could not close the music panel.", exc_info=True)
        self.panel_message = None


class MusicPlayerEvents(commands.Cog):
    """Refresh current panels and handle Lavalink playback lifecycle events."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._next_lavalink_retry = 0.0
        self.refresh_music_panels.start()

    def cog_unload(self) -> None:
        self.refresh_music_panels.cancel()

    @tasks.loop(seconds=15)
    async def refresh_music_panels(self) -> None:
        manager = getattr(self.bot, "music_manager", None)
        if manager is None:
            return
        node = getattr(manager, "node", None)
        if node is None:
            now = asyncio.get_running_loop().time()
            if getattr(manager, "password", "") and now >= self._next_lavalink_retry:
                self._next_lavalink_retry = now + 60
                await manager.connect(attempts=1, timeout=5.0)
            return
        if node.status is not wavelink.NodeStatus.CONNECTED:
            return

        for player in node.players.values():
            if isinstance(player, AegisPlayer) and player.current is not None:
                await player.update_panel()

    @refresh_music_panels.before_loop
    async def before_refresh_music_panels(self) -> None:
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_wavelink_track_start(
        self, payload: wavelink.TrackStartEventPayload
    ) -> None:
        if isinstance(payload.player, AegisPlayer):
            await payload.player.update_panel()

    @commands.Cog.listener()
    async def on_wavelink_track_end(
        self, payload: wavelink.TrackEndEventPayload
    ) -> None:
        if isinstance(payload.player, AegisPlayer):
            await asyncio.sleep(0.1)
            await payload.player.update_panel()

    @commands.Cog.listener()
    async def on_wavelink_track_exception(
        self, payload: wavelink.TrackExceptionEventPayload
    ) -> None:
        if isinstance(payload.player, AegisPlayer):
            logger.warning(
                "Lavalink could not play a track in guild %s: %s",
                payload.player.guild.id if payload.player.guild else "unknown",
                getattr(payload.exception, "message", "unknown track error"),
            )
            await payload.player.update_panel()

    @commands.Cog.listener()
    async def on_wavelink_track_stuck(
        self, payload: wavelink.TrackStuckEventPayload
    ) -> None:
        if isinstance(payload.player, AegisPlayer):
            logger.warning(
                "A track became stuck in guild %s.",
                payload.player.guild.id if payload.player.guild else "unknown",
            )

    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        if not isinstance(player, AegisPlayer):
            return
        await player.close_panel("Disconnected after the voice channel became inactive.")
        try:
            await player.disconnect()
        except (discord.HTTPException, wavelink.LavalinkException):
            logger.warning("Could not disconnect an inactive music player.", exc_info=True)

    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        logger.info("Lavalink node %s is ready.", payload.node.identifier)

    @commands.Cog.listener()
    async def on_wavelink_node_closed(self, node: wavelink.Node, players: list[Any]) -> None:
        logger.warning("Lavalink node %s closed; affected players: %s.", node.identifier, len(players))
