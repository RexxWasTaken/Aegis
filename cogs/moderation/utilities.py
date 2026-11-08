"""Shared parsers and confirmation views for bulk moderation commands."""

from __future__ import annotations

import re

import discord
from discord.ext import commands


MAX_BULK_TARGETS = 10
_USER_TOKEN = re.compile(r"^(?:<@!?(\d{15,20})>|(\d{15,20}))$")


def parse_bulk_member_arguments(
    value: str,
    command_name: str,
) -> tuple[list[str], str]:
    """Parse leading user mentions/IDs followed by an optional reason."""
    target_tokens: list[str] = []
    reason_tokens: list[str] = []
    collecting_targets = True
    for token in value.split():
        if collecting_targets and _USER_TOKEN.fullmatch(token):
            target_tokens.append(token)
        else:
            collecting_targets = False
            reason_tokens.append(token)
    if not 2 <= len(target_tokens) <= MAX_BULK_TARGETS:
        raise commands.BadArgument(
            f"{command_name.title()} must include between 2 and "
            f"{MAX_BULK_TARGETS} unique members."
        )
    return target_tokens, " ".join(reason_tokens) or "No reason provided."


class BulkActionConfirmationView(discord.ui.View):
    """Author-only Confirm/Cancel UI used before bulk moderation actions."""

    def __init__(self, author_id: int, timeout: float = 30) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.value: bool | None = None

    async def _authorize(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the moderator who started this action can confirm it.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._authorize(interaction):
            return
        self.value = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        if not await self._authorize(interaction):
            return
        self.value = False
        await interaction.response.defer()
        self.stop()
