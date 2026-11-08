"""Interactive, owner-only Help menus built from live command registries."""

from __future__ import annotations

from collections import defaultdict
from math import ceil
from typing import TYPE_CHECKING

import discord

from core.emoji_manager import emoji_markup
from embeds.help import help_category_page, help_front_page

if TYPE_CHECKING:
    from discord.ext import commands


PAGE_SIZE = 8
_CATEGORY_EMOJIS = {
    "Ticket": "ticket",
    "Giveaway": "giveaway",
    "Moderation": "moderation",
    "Other": "folder",
}


def _category_for(command: object) -> str:
    qualified_name = str(getattr(command, "qualified_name", "")).lower()
    cog_name = str(getattr(command, "cog_name", "") or "").lower()
    binding = getattr(command, "binding", None)
    cog_name = cog_name or type(binding).__name__.lower()
    if qualified_name.startswith("ticket") or "ticket" in cog_name:
        return "Ticket"
    if qualified_name == "giveaway" or qualified_name.startswith("giveaway ") or (
        "giveaway" in cog_name
    ):
        return "Giveaway"
    if "moderation" in cog_name or qualified_name in {
        "ban", "unban", "softban", "tempban", "massban", "kick", "masskick",
        "timeout", "untimeout", "mute", "unmute", "voicemute", "voiceunmute",
        "deafen", "undeafen", "disconnect", "move", "warn", "unwarn", "warninfo",
        "warnings", "warnlist", "warnstats", "clearwarnings", "purge", "purgeuser",
        "purgebots", "purgehumans", "purgelinks", "purgeinvites", "purgeimages",
        "purgefiles", "purgeembeds", "purgementions", "purgecontains", "purgeafter",
        "lock", "unlock", "lockall", "unlockall", "slowmode", "nick", "resetnick",
        "jail", "unjail",
    }:
        return "Moderation"
    return "Other"


def discover_commands(bot: commands.Bot) -> dict[str, dict[str, list[tuple[str, str]]]]:
    """Read registered prefix and application commands without a hard-coded catalog."""
    registry: dict[str, dict[str, list[tuple[str, str]]]] = {
        "prefix": defaultdict(list),
        "slash": defaultdict(list),
    }
    for command in bot.walk_commands():
        qualified_name = str(command.qualified_name)
        if qualified_name == "help" or getattr(command, "hidden", False):
            continue
        signature = str(getattr(command, "signature", "") or "").strip()
        usage = f"a!{qualified_name} {signature}".strip()
        description = str(getattr(command, "help", None) or getattr(command, "short_doc", ""))
        registry["prefix"][_category_for(command)].append((usage, description))

    for command in bot.tree.walk_commands():
        qualified_name = str(command.qualified_name)
        if qualified_name == "help" or getattr(command, "hidden", False):
            continue
        description = str(getattr(command, "description", "") or "")
        registry["slash"][_category_for(command)].append(
            (f"/{qualified_name}", description)
        )

    for mode in registry:
        for entries in registry[mode].values():
            entries.sort(key=lambda entry: entry[0].casefold())
    return registry


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, view: HelpView) -> None:
        options = [
            discord.SelectOption(
                label=category,
                value=category,
                emoji=discord.PartialEmoji.from_str(
                    emoji_markup(_CATEGORY_EMOJIS.get(category, "folder"))
                ),
            )
            for category in view.categories
        ]
        super().__init__(
            placeholder="Choose a Help category",
            min_values=1,
            max_values=1,
            options=options[:25],
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.category = self.values[0]
        view.page = 1
        await view.refresh(interaction)


class HelpModeSelect(discord.ui.Select):
    def __init__(self) -> None:
        super().__init__(
            placeholder="Choose Prefix or Slash commands",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Prefix Commands", value="prefix"),
                discord.SelectOption(label="Slash Commands", value="slash"),
            ],
            row=1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.mode = self.values[0]
        view.page = 1
        await view.refresh(interaction)


class HelpView(discord.ui.View):
    """Paginated Help UI restricted to the user who invoked the command."""

    def __init__(self, bot: commands.Bot, author_id: int, timeout: float = 180) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.registry = discover_commands(bot)
        all_categories = {
            category
            for mode in self.registry.values()
            for category, entries in mode.items()
            if entries
        }
        self.categories = sorted(
            all_categories,
            key=lambda name: (
                {"Ticket": 0, "Giveaway": 1, "Moderation": 2}.get(name, 3),
                name.casefold(),
            ),
        )
        self.mode = "prefix"
        self.category: str | None = None
        self.page = 1
        self.message: discord.Message | None = None
        self._build_items()

    async def authorized(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        await interaction.response.send_message(
            "Only the person who opened this Help menu can use it.",
            ephemeral=True,
        )
        return False

    def _page_data(self) -> tuple[discord.Embed, int]:
        if self.category is None:
            counts = {
                category: max(
                    len(self.registry["prefix"].get(category, [])),
                    len(self.registry["slash"].get(category, [])),
                )
                for category in self.categories
            }
            return help_front_page(
                prefix_count=sum(map(len, self.registry["prefix"].values())),
                slash_count=sum(map(len, self.registry["slash"].values())),
                category_counts=counts,
            ), 1
        entries = self.registry[self.mode].get(self.category, [])
        page_count = max(1, ceil(len(entries) / PAGE_SIZE))
        self.page = min(max(self.page, 1), page_count)
        offset = (self.page - 1) * PAGE_SIZE
        return help_category_page(
            category=self.category,
            mode="prefix" if self.mode == "prefix" else "slash",
            entries=entries[offset : offset + PAGE_SIZE],
            page=self.page,
            page_count=page_count,
        ), page_count

    def _build_items(self) -> None:
        self.clear_items()
        if self.categories:
            self.add_item(HelpCategorySelect(self))
        self.add_item(HelpModeSelect())
        self.add_item(HelpHomeButton())
        previous = HelpPreviousButton()
        next_button = HelpNextButton()
        self.add_item(previous)
        self.add_item(next_button)
        self.add_item(HelpCloseButton())
        _, page_count = self._page_data()
        previous.disabled = self.category is None or self.page <= 1
        next_button.disabled = self.category is None or self.page >= page_count

    async def refresh(self, interaction: discord.Interaction) -> None:
        self._build_items()
        embed, _ = self._page_data()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HelpHomeButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Home", style=discord.ButtonStyle.primary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.category = None
        view.page = 1
        await view.refresh(interaction)


class HelpPreviousButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Previous", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        if view.category is not None:
            view.page -= 1
        await view.refresh(interaction)


class HelpNextButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Next", style=discord.ButtonStyle.secondary, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        if view.category is not None:
            view.page += 1
        await view.refresh(interaction)


class HelpCloseButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Close", style=discord.ButtonStyle.danger, row=2)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.stop()
        for item in view.children:
            item.disabled = True
        await interaction.response.edit_message(view=view)
