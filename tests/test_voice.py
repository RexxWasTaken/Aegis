from __future__ import annotations

import unittest
from types import SimpleNamespace

from cogs.voice import voice_state_summary


class VoiceCommandTests(unittest.TestCase):
    def test_voice_summary_reports_only_active_flags(self) -> None:
        state = SimpleNamespace(
            self_mute=True,
            self_deaf=False,
            mute=False,
            deaf=True,
            self_stream=False,
            self_video=True,
            suppress=False,
        )
        self.assertEqual(
            voice_state_summary(state),
            "Self-muted, Server-deafened, Camera on",
        )

    def test_voice_summary_reports_an_unrestricted_state(self) -> None:
        state = SimpleNamespace(
            self_mute=False,
            self_deaf=False,
            mute=False,
            deaf=False,
            self_stream=False,
            self_video=False,
            suppress=False,
        )
        self.assertIn("No mute", voice_state_summary(state))


if __name__ == "__main__":
    unittest.main()
