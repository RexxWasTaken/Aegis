from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from core.games import (
    GuessNumberView,
    RockPaperScissorsView,
    TicTacToeView,
    decide_rps,
)


class GameViewTests(unittest.IsolatedAsyncioTestCase):
    def test_tic_tac_toe_detects_wins_and_unfinished_boards(self) -> None:
        self.assertEqual(
            TicTacToeView.winner_for(["X", "X", "X", "O", None, "O", None, None, None]),
            "X",
        )
        self.assertIsNone(
            TicTacToeView.winner_for(["X", "O", "X", "O", "X", "O", "O", "X", "O"])
        )
        self.assertIsNone(TicTacToeView.winner_for([None] * 9))

    async def test_tic_tac_toe_enforces_turns_and_player_validation(self) -> None:
        view = TicTacToeView(10, 20)
        wrong_turn = SimpleNamespace(
            user=SimpleNamespace(id=20),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        await view.play(wrong_turn, 0)
        wrong_turn.response.send_message.assert_awaited_once()
        self.assertIsNone(view.board[0])

        outsider = SimpleNamespace(
            user=SimpleNamespace(id=30),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        await view.play(outsider, 0)
        outsider.response.send_message.assert_awaited_once()
        self.assertIsNone(view.board[0])

    def test_rock_paper_scissors_outcomes_are_correct(self) -> None:
        self.assertEqual(decide_rps("rock", "scissors"), "win")
        self.assertEqual(decide_rps("paper", "scissors"), "loss")
        self.assertEqual(decide_rps("rock", "rock"), "tie")
        with self.assertRaises(ValueError):
            decide_rps("laser", "rock")

    async def test_number_game_rejects_other_players_and_finishes_on_correct_guess(self) -> None:
        view = GuessNumberView(player_id=10, target=3)
        outsider = SimpleNamespace(
            user=SimpleNamespace(id=99),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        await view.play_guess(outsider, 3)
        outsider.response.send_message.assert_awaited_once()
        self.assertTrue(view.active)

        player = SimpleNamespace(
            user=SimpleNamespace(id=10),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )
        await view.play_guess(player, 3)
        self.assertFalse(view.active)
        self.assertEqual(view.result, "win")
        player.response.edit_message.assert_awaited_once()
        self.assertTrue(all(button.disabled for button in view.buttons))


if __name__ == "__main__":
    unittest.main()
