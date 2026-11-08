"""Interactive, owner-only Help menus built from live command registries."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, Any

import discord

from core.emoji_manager import emoji_markup
from embeds.help import help_category_page, help_command_details, help_front_page

if TYPE_CHECKING:
    from discord.ext import commands


PAGE_SIZE = 5
CATEGORY_ORDER = (
    "Automod",
    "Moderation",
    "Welcome",
    "Music",
    "Ticket",
    "Giveaway",
    "Security",
    "Utility",
    "AI",
    "Owner",
)
CATEGORY_EMOJIS = {
    "Automod": "antinuke",
    "Moderation": "moderation",
    "Welcome": "welcomer",
    "Music": "music",
    "Ticket": "ticket",
    "Giveaway": "giveaway",
    "Security": "security",
    "Utility": "utility",
    "AI": "ai",
    "Owner": "owner",
}
_MODERATION_COMMANDS = {
    "ban", "unban", "softban", "tempban", "massban", "kick", "masskick",
    "timeout", "untimeout", "mute", "unmute", "voicemute", "voiceunmute",
    "deafen", "undeafen", "disconnect", "move", "warn", "unwarn", "warninfo",
    "warnings", "warnlist", "warnstats", "clearwarnings", "purge", "purgeuser",
    "purgebots", "purgehumans", "purgelinks", "purgeinvites", "purgeimages",
    "purgefiles", "purgeembeds", "purgementions", "purgecontains", "purgeafter",
    "lock", "unlock", "lockall", "unlockall", "slowmode", "nick", "resetnick",
    "jail", "unjail",
}


@dataclass(frozen=True)
class CommandInfo:
    """Accurate command metadata for Help pages and individual lookups."""

    name: str
    qualified_name: str
    usage: str
    aliases: tuple[str, ...]
    description: str
    permissions: tuple[str, ...]
    examples: tuple[str, ...]
    category: str


def _category_for(command: object) -> str:
    qualified_name = str(getattr(command, "qualified_name", "")).lower()
    cog_name = str(getattr(command, "cog_name", "") or "").lower()
    binding = getattr(command, "binding", None)
    if not cog_name and binding is not None:
        cog_name = type(binding).__name__.lower()
    if qualified_name == "help":
        return "Utility"
    if qualified_name == "ticket" or qualified_name.startswith("ticket ") or "ticket" in cog_name:
        return "Ticket"
    if qualified_name == "giveaway" or qualified_name.startswith("giveaway ") or (
        "giveaway" in cog_name
    ):
        return "Giveaway"
    if "moderation" in cog_name or qualified_name.split(" ")[0] in _MODERATION_COMMANDS:
        return "Moderation"
    for token, category in (
        ("antinuke", "Automod"),
        ("automod", "Automod"),
        ("welcome", "Welcome"),
        ("music", "Music"),
        ("security", "Security"),
        ("utility", "Utility"),
        ("owner", "Owner"),
        ("ai", "AI"),
    ):
        if token in cog_name:
            return category
    cleaned_name = cog_name.removesuffix("cog").replace("_", " ").strip()
    if cleaned_name:
        return " ".join(part.capitalize() for part in cleaned_name.split())
    return "Utility"


def _extras(command: object) -> dict[str, Any]:
    value = getattr(command, "extras", None)
    return value if isinstance(value, dict) else {}


def _permission_labels(command: object) -> tuple[str, ...]:
    extras = _extras(command)
    explicit = extras.get("help_permissions") or extras.get("required_permissions")
    labels: set[str] = set()
    if isinstance(explicit, str):
        labels.update(part.strip() for part in explicit.split(",") if part.strip())
    elif explicit:
        labels.update(str(part).replace("_", " ").title() for part in explicit)

    for check in getattr(command, "checks", ()):
        check_name = getattr(check, "__qualname__", "")
        closure_values = [
            cell.cell_contents
            for cell in (getattr(check, "__closure__", None) or ())
        ]
        if "has_guild_permissions" in check_name:
            for value in closure_values:
                if isinstance(value, dict):
                    labels.update(
                        permission.replace("_", " ").title()
                        for permission, enabled in value.items()
                        if enabled
                    )
        elif "has_guild_permission" in check_name:
            labels.update(
                value.replace("_", " ").title()
                for value in closure_values
                if isinstance(value, str)
            )
    return tuple(sorted(labels, key=str.casefold))


def _examples(command: object) -> tuple[str, ...]:
    values = _extras(command).get("examples") or getattr(command, "examples", ())
    if isinstance(values, str):
        values = (values,)
    return tuple(str(value).strip() for value in values if str(value).strip())


def _slash_usage(command: object) -> str:
    qualified_name = str(getattr(command, "qualified_name", ""))
    parts = [f"/{qualified_name}"]
    for parameter in getattr(command, "parameters", ()):
        name = str(getattr(parameter, "name", "")).strip()
        if not name:
            continue
        parts.append(
            f"<{name}>" if getattr(parameter, "required", False) else f"[{name}]"
        )
    return " ".join(parts)


def _prefix_info(command: commands.Command[Any, ..., Any]) -> CommandInfo:
    qualified_name = str(command.qualified_name)
    signature = str(getattr(command, "signature", "") or "").strip()
    usage = f"a!{qualified_name} {signature}".strip()
    description = str(command.help or command.short_doc or "").strip()
    return CommandInfo(
        name=command.name,
        qualified_name=qualified_name,
        usage=usage,
        aliases=tuple(command.aliases),
        description=description or "No description is documented.",
        permissions=_permission_labels(command),
        examples=_examples(command),
        category=_category_for(command),
    )


def _slash_info(command: object, prefix_command: object | None = None) -> CommandInfo:
    qualified_name = str(getattr(command, "qualified_name", ""))
    description = str(getattr(command, "description", "") or "").strip()
    aliases = tuple(getattr(prefix_command, "aliases", ()) or ())
    permission_source = prefix_command if prefix_command is not None else command
    return CommandInfo(
        name=qualified_name.rsplit(" ", 1)[-1],
        qualified_name=qualified_name,
        usage=_slash_usage(command),
        aliases=aliases,
        description=description or "No description is documented.",
        permissions=_permission_labels(permission_source),
        examples=_examples(permission_source),
        category=_category_for(command),
    )


def discover_commands(
    bot: commands.Bot,
) -> dict[str, dict[str, list[CommandInfo]]]:
    """Read registered prefix and application commands without a fake catalog."""
    registry: dict[str, dict[str, list[CommandInfo]]] = {
        "prefix": defaultdict(list),
        "slash": defaultdict(list),
    }
    for command in bot.walk_commands():
        qualified_name = str(command.qualified_name)
        if qualified_name == "help" or getattr(command, "hidden", False):
            continue
        info = _prefix_info(command)
        registry["prefix"][info.category].append(info)

    for command in bot.tree.walk_commands():
        qualified_name = str(command.qualified_name)
        if qualified_name == "help" or getattr(command, "hidden", False):
            continue
        prefix_command = bot.get_command(qualified_name)
        info = _slash_info(command, prefix_command)
        registry["slash"][info.category].append(info)

    for categories in registry.values():
        for entries in categories.values():
            entries.sort(key=lambda entry: entry.qualified_name.casefold())
    return registry


def ordered_categories(
    registry: dict[str, dict[str, list[CommandInfo]]],
    mode: str | None = None,
) -> list[str]:
    source = (
        registry.get(mode, {})
        if mode is not None
        else {
            category: entries
            for categories in registry.values()
            for category, entries in categories.items()
        }
    )
    names = {
        category
        for category, entries in source.items()
        if entries
    }
    preferred = [category for category in CATEGORY_ORDER if category in names]
    additional = sorted(names.difference(CATEGORY_ORDER), key=str.casefold)
    return preferred + additional


def find_command(bot: commands.Bot, query: str) -> CommandInfo | None:
    """Resolve a registered prefix name or alias, then a slash command name."""
    normalized = query.strip().removeprefix("a!").strip()
    prefix = bot.get_command(normalized)
    if prefix is not None and not getattr(prefix, "hidden", False):
        return _prefix_info(prefix)
    slash_name = normalized.removeprefix("/")
    slash = next(
        (
            command
            for command in bot.tree.walk_commands()
            if command.qualified_name.casefold() == slash_name.casefold()
        ),
        None,
    )
    if slash is None or getattr(slash, "hidden", False):
        return None
    return _slash_info(slash, bot.get_command(slash_name))


class HelpModeSelect(discord.ui.Select):
    def __init__(self, view: HelpView, mode: str) -> None:
        self.mode = mode
        categories = ordered_categories(view.registry, mode)
        options = [
            discord.SelectOption(
                label=category,
                value=category,
                emoji=discord.PartialEmoji.from_str(
                    emoji_markup(CATEGORY_EMOJIS[category])
                )
                if category in CATEGORY_EMOJIS
                else None,
            )
            for category in categories[:25]
        ]
        label = "Prefix Commands" if mode == "prefix" else "Slash Commands"
        super().__init__(
            placeholder=label,
            min_values=1,
            max_values=1,
            options=options,
            row=0 if mode == "prefix" else 1,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.mode = self.mode
        view.category = self.values[0]
        view.page = 1
        await view.refresh(interaction)


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, view: HelpView) -> None:
        options = [
            discord.SelectOption(
                label=category,
                value=category,
                emoji=discord.PartialEmoji.from_str(
                    emoji_markup(CATEGORY_EMOJIS[category])
                )
                if category in CATEGORY_EMOJIS
                else None,
            )
            for category in ordered_categories(view.registry, view.mode)[:25]
        ]
        super().__init__(
            placeholder="Choose a Help category",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.category = self.values[0]
        view.page = 1
        await view.refresh(interaction)


class HelpView(discord.ui.View):
    """Paginated Help UI restricted to the user who invoked the command."""

    def __init__(self, bot: commands.Bot, author_id: int, timeout: float = 180) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.author_id = author_id
        self.registry = discover_commands(bot)
        self.categories = ordered_categories(self.registry)
        self.mode = "prefix"
        self.category: str | None = None
        self.page = 1
        self.message: discord.Message | None = None
        self._build_items()

    async def authorized(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.author_id:
            return True
        try:
            await interaction.response.send_message(
                "Only the person who opened this Help menu can use it.",
                ephemeral=True,
            )
        except discord.HTTPException:
            return False
        return False

    def _page_data(self) -> tuple[discord.Embed, int]:
        if self.category is None:
            return help_front_page(self.categories), 1
        entries = self.registry[self.mode].get(self.category, [])
        page_count = max(1, ceil(len(entries) / PAGE_SIZE))
        self.page = min(max(self.page, 1), page_count)
        offset = (self.page - 1) * PAGE_SIZE
        return help_category_page(
            category=self.category,
            mode=self.mode,
            entries=entries[offset : offset + PAGE_SIZE],
            page=self.page,
            page_count=page_count,
        ), page_count

    def _build_items(self) -> None:
        self.clear_items()
        if self.category is None:
            if ordered_categories(self.registry, "prefix"):
                self.add_item(HelpModeSelect(self, "prefix"))
            if ordered_categories(self.registry, "slash"):
                self.add_item(HelpModeSelect(self, "slash"))
            self.add_item(HelpCloseButton())
            return
        if ordered_categories(self.registry, self.mode):
            self.add_item(HelpCategorySelect(self))
        _, page_count = self._page_data()
        previous = HelpPreviousButton()
        next_button = HelpNextButton()
        previous.disabled = self.page <= 1
        next_button.disabled = self.page >= page_count
        self.add_item(previous)
        self.add_item(next_button)
        self.add_item(HelpHomeButton())
        self.add_item(HelpCloseButton())

    async def refresh(self, interaction: discord.Interaction) -> None:
        self._build_items()
        embed, _ = self._page_data()
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except discord.HTTPException:
            self.stop()

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
        super().__init__(
            label="Home",
            emoji=discord.PartialEmoji.from_str(emoji_markup("home")),
            style=discord.ButtonStyle.primary,
            row=4,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.category = None
        view.page = 1
        await view.refresh(interaction)


class HelpPreviousButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Previous", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.page -= 1
        await view.refresh(interaction)


class HelpNextButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Next", style=discord.ButtonStyle.secondary, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.page += 1
        await view.refresh(interaction)


class HelpCloseButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Close", style=discord.ButtonStyle.danger, row=4)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, HelpView) or not await view.authorized(interaction):
            return
        view.stop()
        try:
            await interaction.response.edit_message(view=None)
        except discord.HTTPException:
            pass


async def send_command_details(
    ctx: commands.Context,
    info: CommandInfo,
) -> None:
    embed = help_command_details(info)
    if ctx.interaction is not None:
        await ctx.send(embed=embed, ephemeral=True)
    else:
        await ctx.send(embed=embed)
