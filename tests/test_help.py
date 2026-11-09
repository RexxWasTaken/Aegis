from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.emoji_manager import emoji_markup
from core.help_view import HelpView, discover_commands, find_command, ordered_categories
from embeds.help import help_category_page, help_command_details, help_front_page


def _permission_check():
    permissions = {"manage_guild": True}

    def predicate():
        return permissions

    predicate.__qualname__ = "has_guild_permissions.<locals>.predicate"
    return predicate


def _prefix_command(
    name: str,
    *,
    qualified_name: str | None = None,
    cog_name: str,
    aliases: tuple[str, ...] = (),
    signature: str = "",
    description: str = "Registered command description.",
    checks: tuple[object, ...] = (),
    hidden: bool = False,
):
    return SimpleNamespace(
        name=name,
        qualified_name=qualified_name or name,
        cog_name=cog_name,
        binding=None,
        aliases=aliases,
        signature=signature,
        help=description,
        short_doc=description,
        checks=checks,
        extras={},
        hidden=hidden,
    )


class _FakeTree:
    def __init__(self, commands):
        self._commands = commands

    def walk_commands(self):
        return iter(self._commands)


class _FakeBot:
    def __init__(self, prefix_commands, slash_commands=()):
        self.default_prefix = "a!"
        self._commands = prefix_commands
        self._by_name = {}
        for command in prefix_commands:
            self._by_name[command.qualified_name] = command
            for alias in command.aliases:
                self._by_name[alias] = command
        self.tree = _FakeTree(slash_commands)

    def walk_commands(self):
        return iter(self._commands)

    def get_command(self, name):
        return self._by_name.get(name)


class HelpTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.ban = _prefix_command(
            "ban",
            cog_name="BanCog",
            aliases=("b", "banuser"),
            signature="<member> [reason]",
            description="Ban a server member and save the moderation case.",
            checks=(_permission_check(),),
        )
        self.hidden = _prefix_command(
            "internal",
            cog_name="OwnerCog",
            hidden=True,
        )
        self.ticket = _prefix_command(
            "info",
            qualified_name="ticket info",
            cog_name="TicketCog",
            signature="",
            description="Show the current ticket state.",
        )
        self.giveaway = _prefix_command(
            "start",
            qualified_name="giveaway start",
            cog_name="GiveawayCog",
            signature="<duration> <winners> <prize>",
            description="Start a reaction-entry giveaway.",
        )
        self.welcome = _prefix_command(
            "welcome",
            cog_name="WelcomeCog",
            description="Configure server welcome messages.",
        )
        self.slash_ticket = SimpleNamespace(
            qualified_name="ticket info",
            cog_name="TicketCog",
            binding=None,
            description="Show the current ticket state.",
            parameters=(SimpleNamespace(name="channel", required=False),),
            hidden=False,
            extras={},
            checks=(),
        )
        self.bot = _FakeBot(
            [self.hidden, self.ban, self.welcome, self.ticket, self.giveaway],
            [self.slash_ticket],
        )

    def test_home_copy_and_registered_categories_follow_required_order(self) -> None:
        registry = discover_commands(self.bot)
        categories = ordered_categories(registry)
        self.assertEqual(categories, ["Moderation", "Welcome", "Ticket", "Giveaway"])

        embed = help_front_page(categories)
        self.assertEqual(embed.title, "Welcome to AEGIS!")
        self.assertEqual(
            embed.description,
            "Your ultimate versatile Discord bot.\n"
            "Use the dropdown menus below to explore command categories.",
        )
        self.assertEqual(
            embed.fields[0].name,
            "Categories",
        )
        self.assertEqual(
            embed.fields[0].value.splitlines(),
            [
                f"{emoji_markup('moderation')} Moderation",
                f"{emoji_markup('welcomer')} Welcome",
                f"{emoji_markup('ticket')} Ticket",
                f"{emoji_markup('giveaway')} Giveaway",
            ],
        )
        self.assertNotIn("Owner", categories)

    def test_lookup_supports_aliases_and_slash_usage_from_registered_parameters(self) -> None:
        by_alias = find_command(self.bot, "b")
        self.assertIsNotNone(by_alias)
        self.assertEqual(by_alias.qualified_name, "ban")
        self.assertEqual(by_alias.usage, "a!ban <member> [reason]")
        self.assertEqual(by_alias.aliases, ("b", "banuser"))
        self.assertEqual(by_alias.permissions, ("Manage Guild",))

        slash = find_command(self.bot, "/ticket info")
        self.assertIsNotNone(slash)
        self.assertEqual(slash.usage, "/ticket info [channel]")
        self.assertEqual(slash.category, "Ticket")

    def test_lookup_and_display_usage_follow_the_active_custom_prefix(self) -> None:
        by_custom_prefix = find_command(self.bot, "?b", prefix="?")
        self.assertIsNotNone(by_custom_prefix)
        self.assertEqual(by_custom_prefix.qualified_name, "ban")
        self.assertEqual(by_custom_prefix.usage, "?ban <member> [reason]")

        view = HelpView(self.bot, author_id=42, prefix="?")
        self.assertEqual(
            view.registry["prefix"]["Moderation"][0].usage,
            "?ban <member> [reason]",
        )

    def test_uncategorized_commands_do_not_get_a_utility_emoji(self) -> None:
        command = _prefix_command(
            "custom",
            cog_name="",
            description="A command without a category.",
        )
        registry = discover_commands(_FakeBot([command]))
        categories = ordered_categories(registry)

        self.assertEqual(categories, ["Uncategorized"])
        embed = help_front_page(categories)
        self.assertEqual(embed.fields[0].value, "Uncategorized")
        self.assertNotIn(emoji_markup("utility"), embed.fields[0].value)

    def test_new_categories_are_ordered_and_parent_groups_are_not_listed(self) -> None:
        welcome_child = _prefix_command(
            "setup",
            qualified_name="welcome setup",
            cog_name="WelcomeCog",
        )
        welcome_group = _prefix_command("welcome", cog_name="WelcomeCog")
        welcome_group.commands = (welcome_child,)
        reaction_child = _prefix_command(
            "add",
            qualified_name="reactionrole add",
            cog_name="ReactionRolesCog",
        )
        logging_child = _prefix_command(
            "events",
            qualified_name="logging events",
            cog_name="LoggingCog",
        )
        slash_commands = [
            SimpleNamespace(
                qualified_name=command.qualified_name,
                cog_name=command.cog_name,
                binding=None,
                description=command.help,
                parameters=(),
                hidden=False,
                extras={},
                checks=(),
            )
            for command in (welcome_child, reaction_child, logging_child)
        ]
        bot = _FakeBot(
            [welcome_group, welcome_child, reaction_child, logging_child],
            slash_commands,
        )

        registry = discover_commands(bot)
        self.assertEqual(
            ordered_categories(registry),
            ["Welcome", "Reaction Roles", "Logging"],
        )
        for mode in ("prefix", "slash"):
            entries = registry[mode]
            self.assertEqual(len(entries["Welcome"]), 1)
            self.assertEqual(len(entries["Reaction Roles"]), 1)
            self.assertEqual(len(entries["Logging"]), 1)
            self.assertNotIn("welcome", {
                item.qualified_name for group in entries.values() for item in group
            })

    def test_help_embeds_respect_discord_field_and_total_character_limits(self) -> None:
        long_entry = SimpleNamespace(
            qualified_name="command" * 100,
            aliases=("alias" * 300,),
            usage="usage" * 300,
            description="description" * 500,
            permissions=("permission" * 200,),
            examples=("example" * 300,),
        )
        page = help_category_page(
            category="Uncategorized" * 100,
            mode="prefix",
            entries=[long_entry] * 5,
            page=1,
            page_count=20,
        )
        details = help_command_details(
            SimpleNamespace(
                category="Uncategorized" * 100,
                description="description" * 1000,
                qualified_name="command" * 1000,
                usage="usage" * 1000,
                aliases=("alias" * 1000,),
                permissions=("permission" * 1000,),
                examples=("example" * 1000,),
            )
        )
        home = help_front_page(["UnknownCategory" * 20 for _ in range(25)])

        for embed in (page, details, home):
            self.assertLessEqual(len(embed), 6000)
            self.assertLessEqual(len(embed.title or ""), 256)
            self.assertLessEqual(len(embed.description or ""), 4096)
            for field in embed.fields:
                self.assertLessEqual(len(field.name), 256)
                self.assertLessEqual(len(field.value), 1024)

    def test_command_details_only_show_recorded_examples_and_permissions(self) -> None:
        info = find_command(self.bot, "ban")
        embed = help_command_details(info)
        self.assertEqual(embed.description, self.ban.help)
        fields = {field.name: field.value for field in embed.fields}
        self.assertEqual(fields["Usage"], "a!ban <member> [reason]")
        self.assertIn("`b`", fields["Aliases"])
        self.assertEqual(fields["Required permissions"], "Manage Guild")
        self.assertEqual(
            fields["Verified examples"],
            "No verified examples are documented.",
        )
        self.assertIn("Moderation", fields["Category"])

    async def test_home_view_has_separate_prefix_and_slash_menus(self) -> None:
        view = HelpView(self.bot, author_id=42)
        labels = [child.placeholder for child in view.children if hasattr(child, "placeholder")]
        self.assertEqual(labels, ["Prefix Commands", "Slash Commands"])

        interaction = SimpleNamespace(
            user=SimpleNamespace(id=7),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        self.assertFalse(await view.authorized(interaction))
        interaction.response.send_message.assert_awaited_once_with(
            "Only the person who opened this Help menu can use it.",
            ephemeral=True,
        )

    def test_category_pagination_shows_every_registered_command(self) -> None:
        commands = [
            _prefix_command(
                f"command_{index}",
                cog_name="UnmappedCog",
                description=f"Command number {index}.",
            )
            for index in range(11)
        ]
        view = HelpView(_FakeBot(commands), author_id=42)
        view.category = "Unmapped"

        first_page, page_count = view._page_data()
        self.assertEqual(page_count, 3)
        self.assertEqual(len(first_page.fields), 5)
        self.assertEqual(first_page.footer.text, "Page 1 of 3")

        names = []
        for page_number in range(1, page_count + 1):
            view.page = page_number
            page, _ = view._page_data()
            names.extend(field.name for field in page.fields)
        self.assertEqual(len(names), 11)
        self.assertEqual(set(names), {f"command_{index}" for index in range(11)})


if __name__ == "__main__":
    unittest.main()
