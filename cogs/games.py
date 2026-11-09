"""Interactive mini-games with player checks and bounded view lifetimes."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.games import GuessNumberView, RockPaperScissorsView, TicTacToeView


class GamesCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="tictactoe",
        aliases=("ttt",),
        description="Start a two-player tic-tac-toe game.",
    )
    @commands.guild_only()
    @app_commands.describe(opponent="The server member you want to challenge.")
    async def tictactoe(
        self,
        ctx: commands.Context,
        opponent: discord.Member,
    ) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if opponent.bot or opponent.id == ctx.author.id:
            await ctx.send(
                "Choose another human server member to play.",
                ephemeral=ctx.interaction is not None,
            )
            return
        view = TicTacToeView(ctx.author.id, opponent.id)
        message = await ctx.send(
            embed=view.embed(),
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        view.message = message

    @commands.hybrid_command(
        name="rps",
        description="Play one round of rock-paper-scissors against AEGIS.",
    )
    async def rps(self, ctx: commands.Context) -> None:
        view = RockPaperScissorsView(ctx.author.id)
        message = await ctx.send(embed=view.embed(), view=view)
        view.message = message

    @commands.hybrid_command(
        name="guess",
        description="Start a private-to-you number guessing round.",
    )
    async def guess(self, ctx: commands.Context) -> None:
        view = GuessNumberView(ctx.author.id)
        message = await ctx.send(
            embed=view.embed(),
            view=view,
            ephemeral=ctx.interaction is not None,
        )
        view.message = message


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GamesCog(bot))
