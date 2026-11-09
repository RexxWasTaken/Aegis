from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database.repositories.community import CommunityRepository


class NewCategoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "aegis.sqlite3"
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()

    async def asyncTearDown(self) -> None:
        await self.repository.close()
        self.temp_dir.cleanup()

    async def test_welcome_reaction_roles_and_logging_survive_restart(self) -> None:
        await self.repository.set_welcome_config(
            guild_id=10,
            kind="welcome",
            channel_id=11,
            message="Welcome {user}",
        )
        await self.repository.set_welcome_config(
            guild_id=10,
            kind="goodbye",
            channel_id=12,
            message="Goodbye {username}",
        )
        panel = await self.repository.create_reaction_role_panel(
            message_id=20,
            guild_id=10,
            channel_id=21,
            created_by=22,
        )
        mapping = await self.repository.add_reaction_role_mapping(
            message_id=panel.message_id,
            guild_id=10,
            emoji_key="unicode:✅",
            emoji="✅",
            role_id=30,
        )
        self.assertEqual(mapping.role_id, 30)
        with self.assertRaises(ValueError):
            await self.repository.add_reaction_role_mapping(
                message_id=panel.message_id,
                guild_id=10,
                emoji_key="unicode:✅",
                emoji="✅",
                role_id=31,
            )
        await self.repository.set_logging_config(
            guild_id=10,
            channel_id=40,
            enabled=True,
            enabled_events=("message_edit", "member_join"),
        )
        await self.repository.set_logging_event(
            guild_id=10,
            event="message_edit",
            enabled=False,
        )
        for kind, target_id in (("channel", 50), ("user", 51), ("role", 52)):
            await self.repository.set_logging_ignore(
                guild_id=10,
                target_type=kind,
                target_id=target_id,
                ignored=True,
            )

        await self.repository.close()
        self.repository = CommunityRepository(self.database_path)
        await self.repository.initialize()

        welcome = await self.repository.get_welcome_config(10)
        self.assertEqual(welcome.welcome_channel_id, 11)
        self.assertEqual(welcome.goodbye_channel_id, 12)
        self.assertTrue(welcome.welcome_enabled)
        self.assertTrue(welcome.goodbye_enabled)
        saved_panel = await self.repository.get_reaction_role_panel(20)
        self.assertEqual(saved_panel.channel_id, 21)
        self.assertEqual(
            await self.repository.list_reaction_role_mappings(20),
            [mapping],
        )
        logging_config = await self.repository.get_logging_config(10)
        self.assertEqual(logging_config.channel_id, 40)
        self.assertEqual(logging_config.enabled_events, ("member_join",))
        self.assertEqual(logging_config.ignored_channels, (50,))
        self.assertEqual(logging_config.ignored_users, (51,))
        self.assertEqual(logging_config.ignored_roles, (52,))

        self.assertTrue(await self.repository.disable_welcome(guild_id=10, kind="welcome"))
        self.assertFalse((await self.repository.get_welcome_config(10)).welcome_enabled)
        self.assertTrue(await self.repository.delete_reaction_role_panel(20))
        self.assertEqual(await self.repository.list_reaction_role_mappings(20), [])


if __name__ == "__main__":
    unittest.main()
