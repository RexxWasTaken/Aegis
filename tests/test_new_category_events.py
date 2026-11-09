from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from cogs.logging import LoggingCog
from core.logging_manager import LoggingManager
from core.reaction_role_manager import ReactionRoleManager
from core.welcome_manager import WelcomeManager
from database.repositories.community import LoggingConfig, ReactionRoleMapping
from embeds.reaction_roles import REACTION_ROLE_TITLE, reaction_role_panel_embed


class NewCategoryEventTests(unittest.IsolatedAsyncioTestCase):
    def test_welcome_message_replaces_only_supported_variables(self) -> None:
        guild = SimpleNamespace(name="Sapphire", member_count=42, members=[1] * 42)
        member = SimpleNamespace(mention="<@55>", name="river", guild=guild)
        rendered = WelcomeManager.render_message(
            "Hi {user} ({username}) at {server}: {member_count}; {other}",
            member,
        )
        self.assertEqual(rendered, "Hi <@55> (river) at Sapphire: 42; {other}")

    def test_role_safety_rejects_powerful_roles(self) -> None:
        safe_permissions = SimpleNamespace(
            administrator=False,
            manage_guild=False,
            manage_roles=False,
            manage_channels=False,
            manage_webhooks=False,
            manage_messages=False,
            manage_threads=False,
            manage_expressions=False,
            manage_events=False,
            ban_members=False,
            kick_members=False,
            moderate_members=False,
            mention_everyone=False,
        )
        role = SimpleNamespace(
            id=20,
            managed=False,
            is_default=lambda: False,
            is_assignable=True,
            position=3,
            permissions=safe_permissions,
        )
        guild = SimpleNamespace(
            id=10,
            me=SimpleNamespace(top_role=SimpleNamespace(position=5)),
        )
        self.assertTrue(ReactionRoleManager.role_is_safe(guild, role))
        role.permissions.administrator = True
        self.assertFalse(ReactionRoleManager.role_is_safe(guild, role))
        role.permissions.administrator = False
        role.permissions.manage_nicknames = True
        self.assertFalse(ReactionRoleManager.role_is_safe(guild, role))
        role.permissions.manage_nicknames = False
        role.permissions.view_audit_log = True
        self.assertFalse(ReactionRoleManager.role_is_safe(guild, role))

    async def test_reaction_add_and_remove_assign_the_saved_role(self) -> None:
        role = SimpleNamespace(
            id=20,
            managed=False,
            is_default=lambda: False,
            is_assignable=True,
            position=3,
            permissions=SimpleNamespace(),
        )
        member = SimpleNamespace(
            id=55,
            bot=False,
            roles=[],
            add_roles=AsyncMock(),
            remove_roles=AsyncMock(),
        )
        guild = SimpleNamespace(
            id=10,
            me=SimpleNamespace(top_role=SimpleNamespace(position=5)),
            get_role=Mock(return_value=role),
            get_member=Mock(return_value=member),
        )
        bot = SimpleNamespace(user=SimpleNamespace(id=1), get_guild=Mock(return_value=guild))
        repository = SimpleNamespace(
            get_reaction_role_mapping=AsyncMock(
                return_value=ReactionRoleMapping(
                    message_id=99,
                    guild_id=10,
                    emoji_key="unicode:✅",
                    emoji="✅",
                    role_id=20,
                )
            )
        )
        manager = ReactionRoleManager(bot, repository)
        payload = SimpleNamespace(
            guild_id=10,
            user_id=55,
            message_id=99,
            emoji=discord.PartialEmoji.from_str("✅"),
            member=member,
        )

        await manager.handle_reaction_add(payload)
        member.add_roles.assert_awaited_once_with(
            role,
            reason="Reaction-role panel selection",
        )
        member.roles.append(role)
        await manager.handle_reaction_remove(payload)
        member.remove_roles.assert_awaited_once_with(
            role,
            reason="Reaction-role panel selection removed",
        )

    async def test_logging_respects_event_and_ignore_filters(self) -> None:
        config = LoggingConfig(
            guild_id=10,
            channel_id=20,
            enabled=True,
            enabled_events=("message_edit",),
            ignored_channels=(30,),
            ignored_users=(40,),
            ignored_roles=(50,),
        )
        self.assertFalse(
            LoggingManager.should_log(config, "message_delete", channel_ids=(31,))
        )
        self.assertFalse(
            LoggingManager.should_log(config, "message_edit", channel_ids=(30,))
        )
        self.assertFalse(
            LoggingManager.should_log(config, "message_edit", user_ids=(40,))
        )
        self.assertFalse(
            LoggingManager.should_log(config, "message_edit", role_ids=(50,))
        )
        self.assertTrue(
            LoggingManager.should_log(config, "message_edit", channel_ids=(31,))
        )

        destination = SimpleNamespace(send=AsyncMock())
        guild = SimpleNamespace(id=10, get_channel=Mock(return_value=destination))
        repository = SimpleNamespace(get_logging_config=AsyncMock(return_value=config))
        manager = LoggingManager(Mock(), repository)
        self.assertFalse(
            await manager.send(
                guild=guild,
                event="message_edit",
                content="ignored",
                channel_ids=(30,),
            )
        )
        self.assertTrue(
            await manager.send(
                guild=guild,
                event="message_edit",
                content="plain log text",
                channel_ids=(31,),
            )
        )
        destination.send.assert_awaited_once()
        self.assertEqual(destination.send.await_args.args, ("plain log text",))
        self.assertNotIn("embed", destination.send.await_args.kwargs)

    async def test_audit_log_permission_errors_do_not_crash_or_guess_executor(self) -> None:
        manager = LoggingManager(Mock(), Mock())
        guild = SimpleNamespace(
            id=10,
            me=SimpleNamespace(
                guild_permissions=SimpleNamespace(view_audit_log=False)
            ),
            audit_logs=Mock(),
        )
        self.assertIsNone(
            await manager.find_executor(
                guild,
                action=discord.AuditLogAction.kick,
                target_id=55,
            )
        )
        guild.audit_logs.assert_not_called()

        guild.me.guild_permissions.view_audit_log = True
        guild.audit_logs = Mock(
            side_effect=discord.Forbidden(response=Mock(), message="Forbidden")
        )
        self.assertIsNone(
            await manager.find_executor(
                guild,
                action=discord.AuditLogAction.kick,
                target_id=55,
            )
        )

    def test_event_listeners_and_reference_panel_are_registered(self) -> None:
        listeners = {name for name, _ in LoggingCog.__cog_listeners__}
        self.assertTrue(
            {
                "on_message_edit",
                "on_raw_message_delete",
                "on_member_join",
                "on_member_remove",
                "on_member_ban",
                "on_member_unban",
                "on_member_update",
                "on_guild_channel_create",
                "on_guild_channel_delete",
                "on_guild_channel_update",
                "on_guild_role_create",
                "on_guild_role_delete",
                "on_guild_role_update",
                "on_voice_state_update",
            }.issubset(listeners)
        )
        mapping = ReactionRoleMapping(99, 10, "unicode:✅", "✅", 20)
        panel = reaction_role_panel_embed((mapping,))
        self.assertEqual(panel.title, REACTION_ROLE_TITLE)
        self.assertIn("✅", panel.description)
        self.assertIn("<@&20>", panel.description)


if __name__ == "__main__":
    unittest.main()
