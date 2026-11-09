"""Player-scoped interactive views for AEGIS mini-games."""

from __future__ import annotations

import random
from typing import Literal

import discord


Mark = Literal["X", "O"]
_WINNING_LINES = (
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
)


def decide_rps(player_choice: str, opponent_choice: str) -> str:
    """Return win, loss, or tie for a rock-paper-scissors round."""
    choices = {"rock", "paper", "scissors"}
    player = player_choice.casefold()
    opponent = opponent_choice.casefold()
    if player not in choices or opponent not in choices:
        raise ValueError("Rock-paper-scissors choices must be rock, paper, or scissors.")
    if player == opponent:
        return "tie"
    wins = {
        ("rock", "scissors"),
        ("paper", "rock"),
        ("scissors", "paper"),
    }
    return "win" if (player, opponent) in wins else "loss"


class _TicTacToeCell(discord.ui.Button["TicTacToeView"]):
    def __init__(self, index: int) -> None:
        self.index = index
        super().__init__(
            label=str(index + 1),
            style=discord.ButtonStyle.secondary,
            row=index // 3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if isinstance(self.view, TicTacToeView):
            await self.view.play(interaction, self.index)


class TicTacToeView(discord.ui.View):
    """A three-by-three match restricted to its two named players."""

    def __init__(
        self,
        player_x_id: int,
        player_o_id: int,
        *,
        timeout: float = 180,
    ) -> None:
        super().__init__(timeout=timeout)
        self.player_x_id = player_x_id
        self.player_o_id = player_o_id
        self.current_player_id = player_x_id
        self.board: list[Mark | None] = [None] * 9
        self.active = True
        self.result: str | None = None
        self.message: discord.Message | None = None
        self.cells: list[_TicTacToeCell] = []
        for index in range(9):
            cell = _TicTacToeCell(index)
            self.cells.append(cell)
            self.add_item(cell)

    @staticmethod
    def winner_for(board: list[Mark | None]) -> Mark | None:
        for first, second, third in _WINNING_LINES:
            mark = board[first]
            if mark is not None and mark == board[second] == board[third]:
                return mark
        return None

    def _symbol(self, user_id: int) -> Mark | None:
        if user_id == self.player_x_id:
            return "X"
        if user_id == self.player_o_id:
            return "O"
        return None

    def _refresh_cells(self) -> None:
        for index, cell in enumerate(self.cells):
            mark = self.board[index]
            cell.label = mark or str(index + 1)
            cell.style = (
                discord.ButtonStyle.primary
                if mark == "X"
                else discord.ButtonStyle.danger
                if mark == "O"
                else discord.ButtonStyle.secondary
            )
            cell.disabled = not self.active or mark is not None

    def embed(self) -> discord.Embed:
        lines = [
            " | ".join(self.board[offset + col] or str(offset + col + 1) for col in range(3))
            for offset in (0, 3, 6)
        ]
        description = f"<@{self.player_x_id}> is **X** • <@{self.player_o_id}> is **O**\n```text\n" + "\n---------\n".join(lines) + "\n```"
        if self.active:
            turn = "X" if self.current_player_id == self.player_x_id else "O"
            description += f"\n<@{self.current_player_id}>'s turn (**{turn}**)."
        elif self.result == "tie":
            description += "\nThe game is a tie."
        elif self.result == "timeout":
            description += "\nThe game ended because time ran out."
        elif self.result in ("X", "O"):
            winner_id = self.player_x_id if self.result == "X" else self.player_o_id
            description += f"\n<@{winner_id}> wins (**{self.result}**)."
        return discord.Embed(
            title="Tic-tac-toe",
            description=description,
            color=discord.Color.blurple(),
        )

    async def play(self, interaction: discord.Interaction, index: int) -> None:
        if not self.active:
            await interaction.response.send_message("This game has ended.", ephemeral=True)
            return
        symbol = self._symbol(interaction.user.id)
        if symbol is None:
            await interaction.response.send_message(
                "Only the two players can make a move.",
                ephemeral=True,
            )
            return
        if interaction.user.id != self.current_player_id:
            await interaction.response.send_message(
                "It is the other player's turn.",
                ephemeral=True,
            )
            return
        if self.board[index] is not None:
            await interaction.response.send_message(
                "That square is already taken.",
                ephemeral=True,
            )
            return
        self.board[index] = symbol
        winner = self.winner_for(self.board)
        if winner is not None:
            self.active = False
            self.result = winner
        elif all(mark is not None for mark in self.board):
            self.active = False
            self.result = "tie"
        else:
            self.current_player_id = (
                self.player_o_id
                if self.current_player_id == self.player_x_id
                else self.player_x_id
            )
        self._refresh_cells()
        await interaction.response.edit_message(
            embed=self.embed(),
            view=self if self.active else None,
        )
        if not self.active:
            self.stop()

    async def on_timeout(self) -> None:
        if not self.active:
            return
        self.active = False
        self.result = "timeout"
        self._refresh_cells()
        if self.message is not None:
            try:
                await self.message.edit(embed=self.embed(), view=self)
            except discord.HTTPException:
                pass


class _RpsButton(discord.ui.Button["RockPaperScissorsView"]):
    def __init__(self, choice: str, label: str, emoji: str) -> None:
        self.choice = choice
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        if isinstance(self.view, RockPaperScissorsView):
            await self.view.play(interaction, self.choice)


class RockPaperScissorsView(discord.ui.View):
    """A one-round versus-bot game owned by the user who started it."""

    def __init__(self, player_id: int, *, timeout: float = 60) -> None:
        super().__init__(timeout=timeout)
        self.player_id = player_id
        self.active = True
        self.player_choice: str | None = None
        self.bot_choice: str | None = None
        self.result: str | None = None
        self.message: discord.Message | None = None
        for choice, label, emoji in (
            ("rock", "Rock", "🪨"),
            ("paper", "Paper", "📄"),
            ("scissors", "Scissors", "✂️"),
        ):
            self.add_item(_RpsButton(choice, label, emoji))

    def embed(self) -> discord.Embed:
        if not self.active and self.player_choice and self.bot_choice:
            outcome = {"win": "You win!", "loss": "I win!", "tie": "It is a tie."}[self.result or "tie"]
            description = (
                f"You chose **{self.player_choice}**; AEGIS chose **{self.bot_choice}**.\n"
                f"**{outcome}**"
            )
        elif self.active:
            description = "Choose Rock, Paper, or Scissors below."
        else:
            description = "The game timed out. Start another round to play."
        return discord.Embed(
            title="Rock, paper, scissors",
            description=description,
            color=discord.Color.blurple(),
        )

    async def play(self, interaction: discord.Interaction, choice: str) -> None:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "Only the person who started this round can play it.",
                ephemeral=True,
            )
            return
        if not self.active:
            await interaction.response.send_message("This round has ended.", ephemeral=True)
            return
        self.player_choice = choice
        self.bot_choice = random.choice(("rock", "paper", "scissors"))
        self.result = decide_rps(self.player_choice, self.bot_choice)
        self.active = False
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=self.embed(), view=self)
        self.stop()

    async def on_timeout(self) -> None:
        if not self.active:
            return
        self.active = False
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(embed=self.embed(), view=self)
            except discord.HTTPException:
                pass


class _GuessButton(discord.ui.Button["GuessNumberView"]):
    def __init__(self, number: int) -> None:
        self.number = number
        super().__init__(label=str(number), style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        if isinstance(self.view, GuessNumberView):
            await self.view.play_guess(interaction, self.number)


class GuessNumberView(discord.ui.View):
    """A five-number guessing game for one player with three attempts."""

    def __init__(
        self,
        player_id: int,
        target: int | None = None,
        *,
        timeout: float = 90,
    ) -> None:
        super().__init__(timeout=timeout)
        self.player_id = player_id
        self.target = target if target is not None else random.randint(1, 5)
        if self.target not in range(1, 6):
            raise ValueError("The hidden number must be between 1 and 5.")
        self.attempts_left = 3
        self.active = True
        self.result: str | None = None
        self.message: discord.Message | None = None
        self.buttons = [_GuessButton(number) for number in range(1, 6)]
        for button in self.buttons:
            self.add_item(button)

    def embed(self) -> discord.Embed:
        if self.active:
            description = f"Pick a number from **1 to 5**. Attempts left: **{self.attempts_left}**."
        elif self.result == "win":
            description = f"You guessed **{self.target}**. Nice work!"
        elif self.result == "loss":
            description = f"No attempts left. The number was **{self.target}**."
        else:
            description = "This game timed out."
        return discord.Embed(
            title="Guess the number",
            description=description,
            color=discord.Color.blurple(),
        )

    async def play_guess(self, interaction: discord.Interaction, number: int) -> None:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message(
                "Only the person who started this game can play it.",
                ephemeral=True,
            )
            return
        if not self.active:
            await interaction.response.send_message("This game has ended.", ephemeral=True)
            return
        if number not in range(1, 6):
            await interaction.response.send_message(
                "Choose one of the numbers 1–5.",
                ephemeral=True,
            )
            return
        if number == self.target:
            self.active = False
            self.result = "win"
        else:
            self.attempts_left -= 1
            button = next(item for item in self.buttons if item.number == number)
            button.disabled = True
            button.label = f"{number} ✕"
            if self.attempts_left == 0:
                self.active = False
                self.result = "loss"
        if not self.active:
            for button in self.buttons:
                button.disabled = True
        await interaction.response.edit_message(
            embed=self.embed(),
            view=self,
        )
        if not self.active:
            self.stop()

    async def on_timeout(self) -> None:
        if not self.active:
            return
        self.active = False
        self.result = "timeout"
        for button in self.buttons:
            button.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(embed=self.embed(), view=self)
            except discord.HTTPException:
                pass
