"""Reaction-only giveaway lifecycle with persistent recovery after restarts."""

from __future__ import annotations

import logging
import random
import asyncio
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord

from core.emoji_manager import emoji_markup
from database.repositories.community import CommunityRepository, GiveawayRecord
from embeds.giveaway import giveaway_announcement, giveaway_ended_embed

if TYPE_CHECKING:
    from discord.ext import commands


logger = logging.getLogger(__name__)
GIVEAWAY_EMOJI_ID = 1518667382581760110
MAX_GIVEAWAY_PRIZE_LENGTH = 500


class GiveawayManagerError(RuntimeError):
    """A giveaway operation could not be completed safely."""


class IncompleteParticipantList(GiveawayManagerError):
    """The complete reaction-user list could not be retrieved."""


class GiveawayManager:
    def __init__(self, bot: commands.Bot, repository: CommunityRepository) -> None:
        self.bot = bot
        self.repository = repository
        self._random = random.SystemRandom()
        self._lifecycle_lock = asyncio.Lock()

    async def start(
        self,
        *,
        channel: discord.TextChannel,
        host: discord.Member,
        prize: str,
        duration: timedelta,
        winner_count: int,
    ) -> GiveawayRecord:
        normalized_prize = prize.strip()
        if not normalized_prize:
            raise GiveawayManagerError("A giveaway prize is required.")
        if len(normalized_prize) > MAX_GIVEAWAY_PRIZE_LENGTH:
            raise GiveawayManagerError(
                f"Giveaway prizes must be {MAX_GIVEAWAY_PRIZE_LENGTH} characters or fewer."
            )
        if duration.total_seconds() <= 0:
            raise GiveawayManagerError("Giveaway duration must be greater than zero.")
        if winner_count < 1:
            raise GiveawayManagerError("Winner count must be at least one.")
        ends_at = datetime.now(timezone.utc) + duration
        try:
            message = await channel.send(
                embed=giveaway_announcement(
                    prize=normalized_prize,
                    winner_count=winner_count,
                    host=host,
                    ends_at=ends_at,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            raise GiveawayManagerError(
                "The giveaway announcement could not be posted. Check the bot's "
                "Send Messages and Embed Links permissions."
            ) from exc
        try:
            await message.add_reaction(
                discord.PartialEmoji.from_str(emoji_markup("giveaway"))
            )
        except discord.HTTPException as exc:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            raise GiveawayManagerError(
                f"Could not add the required reaction {emoji_markup('giveaway')}. "
                "Check emoji availability and the bot's Add Reactions permission; "
                "the giveaway was not started."
            ) from exc
        try:
            return await self.repository.create_giveaway(
                message_id=message.id,
                guild_id=channel.guild.id,
                channel_id=channel.id,
                host_id=host.id,
                prize=normalized_prize,
                winner_count=winner_count,
                ends_at=ends_at,
            )
        except Exception:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            raise

    async def _get_message(
        self, giveaway: GiveawayRecord
    ) -> tuple[discord.TextChannel, discord.Message]:
        channel = self.bot.get_channel(giveaway.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(giveaway.channel_id)
            except discord.NotFound as exc:
                raise GiveawayManagerError(
                    "The giveaway channel no longer exists; no winners were selected."
                ) from exc
            except discord.HTTPException as exc:
                raise GiveawayManagerError(
                    "The giveaway channel could not be fetched; no winners were selected."
                ) from exc
        if not isinstance(channel, discord.TextChannel):
            raise GiveawayManagerError(
                "The giveaway channel is not a text channel; no winners were selected."
            )
        try:
            message = await channel.fetch_message(giveaway.message_id)
        except discord.NotFound as exc:
            await self.repository.update_giveaway(
                message_id=giveaway.message_id,
                status="cancelled",
            )
            raise GiveawayManagerError(
                "The giveaway announcement no longer exists; no winners were selected."
            ) from exc
        except discord.HTTPException as exc:
            raise GiveawayManagerError(
                "The announcement could not be fetched; no winners were selected."
            ) from exc
        return channel, message

    async def _participants(
        self, giveaway: GiveawayRecord
    ) -> tuple[discord.TextChannel, list[int]]:
        channel, message = await self._get_message(giveaway)
        reaction = next(
            (
                item
                for item in message.reactions
                if getattr(item.emoji, "id", None) == GIVEAWAY_EMOJI_ID
                and getattr(item.emoji, "name", None) == "giveaway"
            ),
            None,
        )
        if reaction is None:
            raise IncompleteParticipantList(
                f"The required reaction {emoji_markup('giveaway')} is missing; "
                "no winners were selected."
            )
        try:
            users = [user async for user in reaction.users(limit=None)]
        except discord.Forbidden as exc:
            raise IncompleteParticipantList(
                "The full reaction-user list is unavailable. Check Read Message History "
                "and Read Message Reactions permissions; no winners were selected."
            ) from exc
        except discord.HTTPException as exc:
            raise IncompleteParticipantList(
                "The full reaction-user list could not be fetched. No winners were selected."
            ) from exc
        bot_id = self.bot.user.id if self.bot.user is not None else None
        participants = {
            user.id
            for user in users
            if user.id != giveaway.host_id and user.id != bot_id
        }
        return channel, sorted(participants)

    async def end(
        self, message_id: int, *, reroll: bool = False
    ) -> tuple[GiveawayRecord, tuple[int, ...]]:
        async with self._lifecycle_lock:
            return await self._end_locked(message_id, reroll=reroll)

    async def _end_locked(
        self, message_id: int, *, reroll: bool
    ) -> tuple[GiveawayRecord, tuple[int, ...]]:
        giveaway = await self.repository.get_giveaway(message_id)
        if giveaway is None:
            raise GiveawayManagerError("No giveaway is registered for that message ID.")
        if reroll and giveaway.status != "ended":
            raise GiveawayManagerError("Only an ended giveaway can be rerolled.")
        if not reroll and giveaway.status != "active":
            raise GiveawayManagerError("Only an active giveaway can be ended.")

        channel, participants = await self._participants(giveaway)
        eligible = set(participants)
        if reroll:
            eligible.difference_update(giveaway.winners)
        winners = tuple(
            self._random.sample(sorted(eligible), min(giveaway.winner_count, len(eligible)))
        )
        updated = await self.repository.update_giveaway(
            message_id=message_id,
            status="ended",
            winners=winners if not reroll else tuple(dict.fromkeys((*giveaway.winners, *winners))),
        )
        try:
            await channel.send(
                embed=giveaway_ended_embed(
                    giveaway,
                    winners=winners,
                    reroll=reroll,
                ),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            raise GiveawayManagerError(
                "The winner selection is saved, but the announcement could not be sent. "
                "Check Send Messages and Embed Links permissions."
            ) from exc
        return updated, winners

    async def pause(self, message_id: int) -> GiveawayRecord:
        async with self._lifecycle_lock:
            giveaway = await self.repository.get_giveaway(message_id)
            if giveaway is None or giveaway.status != "active":
                raise GiveawayManagerError("Only an active giveaway can be paused.")
            ends_at = datetime.fromisoformat(giveaway.ends_at)
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
            remaining = max(
                1,
                int((ends_at - datetime.now(timezone.utc)).total_seconds()),
            )
            updated = await self.repository.update_giveaway(
                message_id=message_id,
                status="paused",
                paused_seconds=remaining,
            )
            await self._refresh_announcement(updated)
            return updated

    async def resume(self, message_id: int) -> GiveawayRecord:
        async with self._lifecycle_lock:
            giveaway = await self.repository.get_giveaway(message_id)
            if giveaway is None or giveaway.status != "paused":
                raise GiveawayManagerError("Only a paused giveaway can be resumed.")
            remaining = max(1, giveaway.paused_seconds or 1)
            updated = await self.repository.update_giveaway(
                message_id=message_id,
                status="active",
                ends_at=datetime.now(timezone.utc) + timedelta(seconds=remaining),
                paused_seconds=None,
            )
            await self._refresh_announcement(updated)
            return updated

    async def _refresh_announcement(self, giveaway: GiveawayRecord) -> None:
        try:
            channel, message = await self._get_message(giveaway)
            ends_at = datetime.fromisoformat(giveaway.ends_at)
            if ends_at.tzinfo is None:
                ends_at = ends_at.replace(tzinfo=timezone.utc)
            await message.edit(
                embed=giveaway_announcement(
                    prize=giveaway.prize,
                    winner_count=giveaway.winner_count,
                    host=giveaway.host_id,
                    ends_at=ends_at,
                    paused_seconds=(
                        giveaway.paused_seconds if giveaway.status == "paused" else None
                    ),
                )
            )
        except (GiveawayManagerError, discord.HTTPException):
            logger.exception(
                "Could not refresh giveaway announcement %s after a state change",
                giveaway.message_id,
            )

    async def delete(self, message_id: int) -> None:
        async with self._lifecycle_lock:
            await self._delete_locked(message_id)

    async def _delete_locked(self, message_id: int) -> None:
        giveaway = await self.repository.get_giveaway(message_id)
        if giveaway is None:
            raise GiveawayManagerError("No giveaway is registered for that message ID.")
        channel = self.bot.get_channel(giveaway.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(giveaway.channel_id)
            except discord.NotFound:
                channel = None
            except discord.HTTPException as exc:
                raise GiveawayManagerError(
                    "The giveaway channel could not be fetched; its record was kept."
                ) from exc
        if channel is not None:
            if not isinstance(channel, discord.TextChannel):
                raise GiveawayManagerError("The saved giveaway channel is invalid.")
            try:
                message = await channel.fetch_message(message_id)
                await message.delete()
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                raise GiveawayManagerError(
                    "The announcement could not be deleted; its record was kept."
                ) from exc
        await self.repository.delete_giveaway(message_id)

    async def finish_due_giveaways(self) -> None:
        for giveaway in await self.repository.due_giveaways():
            try:
                await self.end(giveaway.message_id)
            except IncompleteParticipantList as exc:
                logger.warning("Giveaway %s remains active: %s", giveaway.message_id, exc)
            except GiveawayManagerError as exc:
                logger.warning("Giveaway %s was not finalized: %s", giveaway.message_id, exc)
            except discord.HTTPException:
                logger.exception(
                    "Discord request failed while finalizing giveaway %s",
                    giveaway.message_id,
                )
