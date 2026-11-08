from __future__ import annotations

import unittest
from types import SimpleNamespace

from core.permissions import (
    ModerationPermissionError,
    ModerationTargetError,
    validate_ban_target,
    validate_kick_target,
    validate_unban_target,
)


def member(
    member_id: int,
    guild: object,
    position: int,
    *,
    can_ban: bool = True,
    is_bot: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=member_id,
        guild=guild,
        top_role=SimpleNamespace(position=position),
        guild_permissions=SimpleNamespace(ban_members=can_ban),
        bot=is_bot,
    )


class ModerationPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guild = SimpleNamespace(id=1, owner_id=99)
        self.moderator = member(10, self.guild, 5)
        self.bot = member(20, self.guild, 10, is_bot=True)
        self.target = member(30, self.guild, 2)

    def test_valid_ban_target_passes(self) -> None:
        validate_ban_target(self.guild, self.target, self.moderator, self.bot)

    def test_moderator_cannot_ban_self(self) -> None:
        with self.assertRaisesRegex(ModerationTargetError, "yourself"):
            validate_ban_target(self.guild, self.moderator, self.moderator, self.bot)

    def test_server_owner_cannot_be_targeted(self) -> None:
        owner = member(99, self.guild, 100)
        with self.assertRaisesRegex(ModerationTargetError, "server owner"):
            validate_ban_target(self.guild, owner, self.moderator, self.bot)

    def test_equal_or_higher_moderator_role_is_protected(self) -> None:
        peer = member(40, self.guild, 5)
        with self.assertRaisesRegex(ModerationTargetError, "equal or higher"):
            validate_ban_target(self.guild, peer, self.moderator, self.bot)

    def test_bot_role_hierarchy_is_enforced(self) -> None:
        high_target = member(40, self.guild, 10)
        owner = member(self.guild.owner_id, self.guild, 20)
        with self.assertRaisesRegex(ModerationTargetError, "bot cannot ban"):
            validate_ban_target(self.guild, high_target, owner, self.bot)

    def test_moderator_and_bot_permissions_are_enforced(self) -> None:
        moderator = member(10, self.guild, 5, can_ban=False)
        with self.assertRaises(ModerationPermissionError):
            validate_ban_target(self.guild, self.target, moderator, self.bot)
        bot_without_permission = member(20, self.guild, 10, can_ban=False, is_bot=True)
        with self.assertRaisesRegex(ModerationPermissionError, "bot needs"):
            validate_ban_target(self.guild, self.target, self.moderator, bot_without_permission)

    def test_cross_guild_target_is_rejected(self) -> None:
        foreign_target = member(40, SimpleNamespace(id=2, owner_id=99), 1)
        with self.assertRaisesRegex(ModerationTargetError, "this server"):
            validate_ban_target(self.guild, foreign_target, self.moderator, self.bot)

    def test_unban_rejects_self_owner_and_bot(self) -> None:
        for target_id in (self.moderator.id, self.guild.owner_id, self.bot.id):
            with self.subTest(target_id=target_id):
                with self.assertRaises(ModerationTargetError):
                    validate_unban_target(self.guild, target_id, self.moderator, self.bot)

    def test_valid_unban_target_passes(self) -> None:
        validate_unban_target(self.guild, 55, self.moderator, self.bot)

    def test_kick_uses_kick_permissions_and_shared_hierarchy_rules(self) -> None:
        self.moderator.guild_permissions.kick_members = True
        self.bot.guild_permissions.kick_members = True
        validate_kick_target(self.guild, self.target, self.moderator, self.bot)
        without_kick = member(10, self.guild, 5, can_ban=True)
        without_kick.guild_permissions.kick_members = False
        with self.assertRaisesRegex(ModerationPermissionError, "Kick Members"):
            validate_kick_target(self.guild, self.target, without_kick, self.bot)

    def test_kick_respects_self_and_server_owner_protections(self) -> None:
        self.moderator.guild_permissions.kick_members = True
        self.bot.guild_permissions.kick_members = True
        with self.assertRaisesRegex(ModerationTargetError, "kick yourself"):
            validate_kick_target(self.guild, self.moderator, self.moderator, self.bot)
        owner = member(99, self.guild, 100)
        with self.assertRaisesRegex(ModerationTargetError, "server owner"):
            validate_kick_target(self.guild, owner, self.moderator, self.bot)


if __name__ == "__main__":
    unittest.main()
