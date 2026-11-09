from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from cogs.information import resolve_channel


class InformationCommandTests(unittest.TestCase):
    def test_channel_resolution_supports_mentions_ids_and_exact_names(self) -> None:
        target = SimpleNamespace(id=12345678901234567, name="general")
        guild = SimpleNamespace(
            get_channel=Mock(return_value=target),
            channels=[target],
        )

        self.assertIs(
            resolve_channel(guild, f"<#{target.id}>"),
            target,
        )
        self.assertIs(resolve_channel(guild, str(target.id)), target)
        self.assertIs(resolve_channel(guild, "#General"), target)
        self.assertIsNone(resolve_channel(guild, "missing"))


if __name__ == "__main__":
    unittest.main()
