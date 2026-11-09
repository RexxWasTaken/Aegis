"""Simple, self-contained games."""

from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands


RPS_CHOICES = ("rock", "paper", "scissors")


class GamesCog(commands.Cog):
    @commands.hybrid_command(
        name="rps",
        description="Play rock-paper-scissors against AEGIS.",
    )
    @app_commands.choices(
        choice=[
            app_commands.Choice(name="Rock", value="rock"),
            app_commands.Choice(name="Paper", value="paper"),
            app_commands.Choice(name="Scissors", value="scissors"),
        ]
    )
    async def rps(self, ctx: commands.Context, choice: str) -> None:
        player_choice = choice.strip().casefold()
        if player_choice not in RPS_CHOICES:
            await ctx.send(
                "Choose rock, paper, or scissors.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        bot_choice = random.choice(RPS_CHOICES)
        if player_choice == bot_choice:
            result = "It's a tie."
        elif (player_choice, bot_choice) in {
            ("rock", "scissors"),
            ("paper", "rock"),
            ("scissors", "paper"),
        }:
            result = "You win."
        else:
            result = "AEGIS wins."
        await ctx.send(
            f"You: **{player_choice}** • AEGIS: **{bot_choice}**\n{result}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="roll",
        description="Roll a die with 2–100 sides.",
    )
    @app_commands.describe(sides="Number of sides; defaults to 6.")
    async def roll(self, ctx: commands.Context, sides: int = 6) -> None:
        if not 2 <= sides <= 100:
            await ctx.send(
                "Choose a die with 2–100 sides.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        await ctx.send(
            f"🎲 You rolled **{random.randint(1, sides)}** on a d{sides}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GamesCog())
