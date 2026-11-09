from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from cogs.security import SecurityCog
from core.security import SecurityManager
from database.repositories.community import SecurityConfig


class StubRepository:
    def __init__(self, config: SecurityConfig) -> None:
        self.config = config
        self.is_security_trusted = AsyncMock(return_value=False)
        self.get_security_config = AsyncMock(return_value=config)


class StubBot:
    def __init__(self) -> None:
        self.user = SimpleNamespace(id=900)
        self.is_owner = AsyncMock(return_value=False)


def _audit_entry(
    *,
    actor: object,
    target_id: int | None = None,
    channel_id: int | None = None,
) -> SimpleNamespace:
    extra = (
        SimpleNamespace(channel=SimpleNamespace(id=channel_id))
        if channel_id is not None
        else None
    )
    target = SimpleNamespace(id=target_id) if target_id is not None else None
    return SimpleNamespace(
        user=actor,
        target=target,
        extra=extra,
        created_at=datetime.now(timezone.utc),
    )


class SecurityManagerTests(unittest.IsolatedAsyncioTestCase):
    def test_event_counter_expires_actions_outside_the_window(self) -> None:
        manager = SecurityManager(StubBot(), StubRepository(SecurityConfig(guild_id=1)))
        self.assertEqual(
            manager.record_event(
                guild_id=1,
                actor_id=2,
                window_seconds=10,
                now=10,
            ),
            1,
        )
        self.assertEqual(
            manager.record_event(
                guild_id=1,
                actor_id=2,
                window_seconds=10,
                now=15,
            ),
            2,
        )
        self.assertEqual(
            manager.record_event(
                guild_id=1,
                actor_id=2,
                window_seconds=10,
                now=26,
            ),
            1,
        )

    async def test_threshold_alerts_once_and_default_log_mode_never_kicks(self) -> None:
        config = SecurityConfig(
            guild_id=1,
            enabled=True,
            threshold=2,
            action="log",
        )
        repository = StubRepository(config)
        manager = SecurityManager(StubBot(), repository)
        actor = SimpleNamespace(id=3, mention="<@3>", bot=False)
        actor.kick = AsyncMock()
        guild = SimpleNamespace(id=1, owner_id=2)

        self.assertFalse(
            await manager.handle_actor_event(
                guild,
                actor,
                event="channel_delete",
                config=config,
            )
        )
        self.assertTrue(
            await manager.handle_actor_event(
                guild,
                actor,
                event="role_delete",
                config=config,
            )
        )
        self.assertFalse(
            await manager.handle_actor_event(
                guild,
                actor,
                event="channel_delete",
                config=config,
            )
        )
        self.assertEqual(len(manager._recent_events[(1, 3)]), 3)
        actor.kick.assert_not_awaited()

    async def test_mass_mention_alerts_on_first_over_limit_message(self) -> None:
        from unittest.mock import Mock

        config = SecurityConfig(
            guild_id=1,
            enabled=True,
            threshold=3,
            mention_limit=5,
            action="log",
        )
        manager = SecurityManager(StubBot(), StubRepository(config))
        guild = SimpleNamespace(id=1, owner_id=2)
        author = Mock(spec=discord.Member)
        author.id = 3
        author.bot = False
        author.mention = "<@3>"
        author.guild = guild
        message = SimpleNamespace(
            guild=guild,
            author=author,
            mentions=[object() for _ in range(5)],
            role_mentions=[],
            mention_everyone=False,
        )

        self.assertTrue(await manager.handle_mass_mention(message))
        self.assertEqual(len(manager._recent_events[(1, 3)]), 1)

    async def test_explicit_kick_mode_checks_bot_permission_and_role_hierarchy(self) -> None:
        class Role:
            def __init__(self, position: int) -> None:
                self.position = position

            def __ge__(self, other: "Role") -> bool:
                return self.position >= other.position

        config = SecurityConfig(
            guild_id=1,
            enabled=True,
            threshold=2,
            action="kick",
        )
        actor = SimpleNamespace(
            id=3,
            mention="<@3>",
            bot=False,
            top_role=Role(1),
            kick=AsyncMock(),
        )
        bot_member = SimpleNamespace(
            top_role=Role(5),
            guild_permissions=SimpleNamespace(kick_members=False),
        )
        guild = SimpleNamespace(
            id=1,
            owner_id=2,
            me=bot_member,
            get_member=lambda user_id: actor if user_id == actor.id else None,
        )
        manager = SecurityManager(StubBot(), StubRepository(config))

        await manager.handle_actor_event(
            guild,
            actor,
            event="channel_delete",
            config=config,
        )
        self.assertTrue(
            await manager.handle_actor_event(
                guild,
                actor,
                event="role_delete",
                config=config,
            )
        )
        actor.kick.assert_not_awaited()

        bot_member.guild_permissions.kick_members = True
        actor.top_role = Role(5)
        manager = SecurityManager(StubBot(), StubRepository(config))
        await manager.handle_actor_event(
            guild,
            actor,
            event="channel_delete",
            config=config,
        )
        await manager.handle_actor_event(
            guild,
            actor,
            event="role_delete",
            config=config,
        )
        actor.kick.assert_not_awaited()

        actor.top_role = Role(1)
        manager = SecurityManager(StubBot(), StubRepository(config))
        await manager.handle_actor_event(
            guild,
            actor,
            event="channel_delete",
            config=config,
        )
        await manager.handle_actor_event(
            guild,
            actor,
            event="role_delete",
            config=config,
        )
        actor.kick.assert_awaited_once()

    async def test_server_owner_bot_owner_and_trusted_members_are_protected(self) -> None:
        config = SecurityConfig(guild_id=1, enabled=True, threshold=2)
        repository = StubRepository(config)
        repository.is_security_trusted = AsyncMock(
            side_effect=lambda *, guild_id, user_id: user_id == 4
        )
        bot = StubBot()
        bot.is_owner = AsyncMock(side_effect=lambda user: user.id == 5)
        manager = SecurityManager(bot, repository)
        guild = SimpleNamespace(id=1, owner_id=2)

        for user_id in (2, 4, 5, 900):
            actor = SimpleNamespace(id=user_id, mention=f"<@{user_id}>", bot=False)
            self.assertFalse(
                await manager.handle_actor_event(
                    guild,
                    actor,
                    event="role_delete",
                    config=config,
                )
            )
        self.assertEqual(manager._recent_events.get((1, 2)), None)
        self.assertEqual(manager._recent_events.get((1, 4)), None)
        self.assertEqual(manager._recent_events.get((1, 5)), None)

    async def test_audit_executor_matches_target_and_webhook_channel(self) -> None:
        actor = SimpleNamespace(id=3)
        entries = {
            discord.AuditLogAction.channel_delete: [
                _audit_entry(actor=actor, target_id=44)
            ],
            discord.AuditLogAction.webhook_create: [
                _audit_entry(actor=actor, target_id=555, channel_id=77)
            ],
        }

        class Guild:
            id = 1
            me = SimpleNamespace(
                guild_permissions=SimpleNamespace(view_audit_log=True)
            )

            def audit_logs(self, *, limit: int, action: discord.AuditLogAction):
                async def iterator():
                    for entry in entries.get(action, []):
                        yield entry

                return iterator()

        manager = SecurityManager(
            StubBot(),
            StubRepository(SecurityConfig(guild_id=1)),
        )
        guild = Guild()
        self.assertIs(
            await manager.find_executor(
                guild,
                event="channel_delete",
                target_id=44,
            ),
            actor,
        )
        self.assertIs(
            await manager.find_executor(
                guild,
                event="webhook_create",
                target_id=None,
                channel_id=77,
            ),
            actor,
        )
        self.assertIsNone(
            await manager.find_executor(
                guild,
                event="channel_delete",
                target_id=999,
            )
        )

    async def test_cog_registers_protection_events_without_side_effects_on_load(self) -> None:
        listener_events = [event for event, _ in SecurityCog.__cog_listeners__]
        listener_names = set(listener_events)
        self.assertEqual(len(listener_events), len(listener_names))
        self.assertTrue(
            {
                "on_guild_channel_create",
                "on_guild_channel_delete",
                "on_guild_channel_update",
                "on_guild_role_create",
                "on_guild_role_delete",
                "on_guild_role_update",
                "on_member_ban",
                "on_member_remove",
                "on_member_join",
                "on_webhooks_update",
                "on_message",
            }.issubset(listener_names)
        )


if __name__ == "__main__":
    unittest.main()
