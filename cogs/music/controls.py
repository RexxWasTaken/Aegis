"""Guild- and voice-checked buttons for the player and queue panels."""

from __future__ import annotations

import logging
from typing import Any

import discord
import wavelink

from cogs.music.queue import build_queue_page, play_previous
from core.emoji_manager import emoji_markup
from embeds.music import queue_embed


logger = logging.getLogger(__name__)


async def authorize_player_interaction(
    interaction: discord.Interaction,
    player: Any,
) -> bool:
    """Allow controls only in the owning guild and the player's voice channel."""
    guild = getattr(player, "guild", None)
    if guild is None or interaction.guild_id != guild.id:
        await interaction.response.send_message(
            "These controls belong to a different server.",
            ephemeral=True,
        )
        return False

    player_channel = getattr(player, "channel", None)
    user_channel = getattr(getattr(interaction.user, "voice", None), "channel", None)
    if (
        player_channel is None
        or user_channel is None
        or player_channel.id != user_channel.id
    ):
        await interaction.response.send_message(
            "Join the player's voice channel to use these controls.",
            ephemeral=True,
        )
        return False
    return True


class _PlayerButton(discord.ui.Button["PlayerControls"]):
    def __init__(
        self,
        player: Any,
        *,
        action: str,
        label: str,
        emoji: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        guild_id = getattr(getattr(player, "guild", None), "id", 0)
        super().__init__(
            label=label,
            emoji=discord.PartialEmoji.from_str(emoji_markup(emoji)),
            style=style,
            custom_id=f"aegis:music:{guild_id}:{action}",
            row=0,
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, PlayerControls):
            return
        if not await authorize_player_interaction(interaction, view.player):
            return

        await interaction.response.defer(ephemeral=True)
        try:
            result = await view.run_action(self.action)
        except (discord.HTTPException, wavelink.LavalinkException, ValueError) as exc:
            logger.warning("Music control %s failed: %s", self.action, exc)
            result = "That player action failed. Try again after Lavalink reconnects."
        if result:
            await interaction.followup.send(result, ephemeral=True)


class PlayerControls(discord.ui.View):
    """The four controls shown beneath the live now-playing card."""

    def __init__(self, player: Any, *, timeout: float = 1800) -> None:
        super().__init__(timeout=timeout)
        self.player = player
        self.add_item(
            _PlayerButton(
                player,
                action="previous",
                label="Previous",
                emoji="previous",
            )
        )
        self.add_item(self._pause_button())
        self.add_item(
            _PlayerButton(
                player,
                action="skip",
                label="Skip",
                emoji="next",
                style=discord.ButtonStyle.primary,
            )
        )
        self.add_item(
            _PlayerButton(
                player,
                action="stop",
                label="Stop",
                emoji="stop",
                style=discord.ButtonStyle.danger,
            )
        )

    def _pause_button(self) -> _PlayerButton:
        paused = bool(getattr(self.player, "paused", False))
        return _PlayerButton(
            self.player,
            action="toggle",
            label="Resume" if paused else "Pause",
            emoji="play" if paused else "pause",
            style=discord.ButtonStyle.success if paused else discord.ButtonStyle.secondary,
        )

    def refresh_state(self) -> None:
        """Update the pause button label and icon before editing the panel."""
        for item in self.children:
            if isinstance(item, _PlayerButton) and item.action == "toggle":
                self.remove_item(item)
                self.add_item(self._pause_button())
                break

    async def run_action(self, action: str) -> str | None:
        player = self.player
        if action == "toggle":
            paused = not bool(player.paused)
            await player.pause(paused)
            await player.update_panel()
            return "Playback paused." if paused else "Playback resumed."
        if action == "previous":
            track = await play_previous(player)
            if track is None:
                return "There is no previous track in this session."
            await player.update_panel()
            return f"Playing {track.title}."
        if action == "skip":
            if player.current is None:
                return "Nothing is playing."
            await player.skip(force=True)
            await player.update_panel()
            return "Skipped the current track."
        if action == "stop":
            player.queue.clear()
            player.auto_queue.clear()
            player.autoplay = wavelink.AutoPlayMode.disabled
            if player.current is not None:
                await player.skip(force=True)
            await player.update_panel()
            return "Stopped playback and cleared the queue."
        return None

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        message = getattr(self.player, "panel_message", None)
        if message is not None:
            try:
                await message.edit(view=self)
            except discord.HTTPException:
                pass
        if getattr(self.player, "panel_view", None) is self:
            self.player.panel_view = None


class _QueuePageButton(discord.ui.Button["QueuePaginationView"]):
    def __init__(self, action: str, label: str, emoji: str, disabled: bool) -> None:
        super().__init__(
            label=label,
            emoji=discord.PartialEmoji.from_str(emoji_markup(emoji)),
            style=discord.ButtonStyle.secondary,
            custom_id=f"aegis:queue:{action}",
            disabled=disabled,
            row=0,
        )
        self.action = action

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, QueuePaginationView):
            return
        if not await authorize_player_interaction(interaction, view.player):
            return

        view.page += -1 if self.action == "previous" else 1
        current = build_queue_page(view.player.queue, view.page)
        view.page = current.page
        view.page_count = current.page_count
        view._refresh_buttons()
        await interaction.response.edit_message(
            embed=queue_embed(
                current.tracks,
                page=current.page,
                page_count=current.page_count,
                total=current.total,
            ),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class QueuePaginationView(discord.ui.View):
    """Small, voice-checked paginator for upcoming tracks."""

    def __init__(
        self,
        player: Any,
        *,
        page: int,
        page_count: int,
        timeout: float = 900,
    ) -> None:
        super().__init__(timeout=timeout)
        self.player = player
        self.page = page
        self.page_count = page_count
        self.message: discord.Message | None = None
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.clear_items()
        self.add_item(
            _QueuePageButton(
                "previous",
                "Previous",
                "larrow",
                self.page <= 1,
            )
        )
        self.add_item(
            _QueuePageButton(
                "next",
                "Next",
                "arrow",
                self.page >= self.page_count,
            )
        )

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
