from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database.repositories.community import CommunityRepository, SecurityConfig


class SecurityRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_security_defaults_are_disabled_and_log_only(self) -> None:
        repository = CommunityRepository(":memory:")
        await repository.initialize()
        try:
            config = await repository.get_security_config(111)
            self.assertEqual(
                config,
                SecurityConfig(guild_id=111),
            )
            self.assertFalse(config.enabled)
            self.assertEqual(config.action, "log")
        finally:
            await repository.close()

    async def test_security_settings_and_trusted_members_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "community.sqlite"
            repository = CommunityRepository(path)
            await repository.initialize()
            saved = await repository.set_security_config(
                SecurityConfig(
                    guild_id=111,
                    enabled=True,
                    threshold=4,
                    window_seconds=20,
                    mention_limit=8,
                    log_channel_id=333,
                    action="kick",
                )
            )
            self.assertEqual(saved.threshold, 4)
            self.assertTrue(
                await repository.add_security_trusted_user(
                    guild_id=111,
                    user_id=222,
                    added_by=444,
                )
            )
            self.assertFalse(
                await repository.add_security_trusted_user(
                    guild_id=111,
                    user_id=222,
                    added_by=444,
                )
            )
            await repository.close()

            reopened = CommunityRepository(path)
            await reopened.initialize()
            try:
                self.assertEqual(
                    await reopened.get_security_config(111),
                    saved,
                )
                self.assertTrue(
                    await reopened.is_security_trusted(guild_id=111, user_id=222)
                )
                self.assertEqual(
                    await reopened.list_security_trusted_users(guild_id=111),
                    [222],
                )
                self.assertTrue(
                    await reopened.remove_security_trusted_user(
                        guild_id=111,
                        user_id=222,
                    )
                )
                self.assertFalse(
                    await reopened.is_security_trusted(guild_id=111, user_id=222)
                )
            finally:
                await reopened.close()

    async def test_invalid_security_settings_are_rejected(self) -> None:
        repository = CommunityRepository(":memory:")
        await repository.initialize()
        try:
            invalid_configs = (
                SecurityConfig(guild_id=111, threshold=1),
                SecurityConfig(guild_id=111, window_seconds=61),
                SecurityConfig(guild_id=111, mention_limit=1),
                SecurityConfig(guild_id=111, action="ban"),
                SecurityConfig(guild_id=111, log_channel_id=0),
                SecurityConfig(guild_id=111, threshold="three"),  # type: ignore[arg-type]
            )
            for config in invalid_configs:
                with self.subTest(config=config):
                    with self.assertRaises(ValueError):
                        await repository.set_security_config(config)
        finally:
            await repository.close()


if __name__ == "__main__":
    unittest.main()
