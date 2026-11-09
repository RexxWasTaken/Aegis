from __future__ import annotations

import unittest

from cogs.logging import LoggingCog
from cogs.reaction_roles import ReactionRolesCog
from cogs.welcome import WelcomeCog
from core.loader import COMMUNITY_EXTENSIONS
from core.help_view import _permission_labels


def _leaf_commands(cog_type: type) -> list[object]:
    return [
        command
        for command in cog_type.__cog_commands__
        if not getattr(command, "commands", ())
    ]


class NewCategoryCommandTests(unittest.TestCase):
    def test_exactly_fifteen_unique_leaf_commands_are_registered(self) -> None:
        expected = {
            WelcomeCog: {
                "welcome setup",
                "welcome test",
                "welcome disable",
                "goodbye setup",
                "goodbye disable",
            },
            ReactionRolesCog: {
                "reactionrole panel",
                "reactionrole add",
                "reactionrole remove",
                "reactionrole list",
                "reactionrole delete",
            },
            LoggingCog: {
                "logging setup",
                "logging events",
                "logging ignore",
                "logging status",
                "logging disable",
            },
        }
        all_names: list[str] = []
        for cog_type, expected_names in expected.items():
            names = [command.qualified_name for command in _leaf_commands(cog_type)]
            self.assertEqual(set(names), expected_names)
            self.assertEqual(len(names), 5)
            all_names.extend(names)
        self.assertEqual(len(all_names), 15)
        self.assertEqual(len(set(all_names)), 15)

    def test_all_management_commands_declare_permission_checks(self) -> None:
        for cog_type in (WelcomeCog, ReactionRolesCog, LoggingCog):
            for command in _leaf_commands(cog_type):
                self.assertTrue(command.checks, command.qualified_name)
                self.assertTrue(
                    _permission_labels(command),
                    f"{command.qualified_name} should document its permission.",
                )

    def test_only_the_three_requested_extensions_were_added(self) -> None:
        self.assertEqual(
            COMMUNITY_EXTENSIONS[-3:],
            (
                "cogs.welcome",
                "cogs.reaction_roles",
                "cogs.logging",
            ),
        )


if __name__ == "__main__":
    unittest.main()
