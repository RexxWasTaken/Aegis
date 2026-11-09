"""Lightweight, offline fun commands."""

from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands


EIGHT_BALL_ANSWERS = (
    "It is certain.",
    "Most likely.",
    "Ask again later.",
    "The signs point to yes.",
    "Don't count on it.",
    "Outlook is unclear.",
)


class FunCog(commands.Cog):
    @commands.hybrid_command(
        name="coinflip",
        description="Flip a coin.",
    )
    async def coinflip(self, ctx: commands.Context) -> None:
        result = random.choice(("Heads", "Tails"))
        await ctx.send(f"🪙 {result}", allowed_mentions=discord.AllowedMentions.none())

    @commands.hybrid_command(
        name="eightball",
        description="Ask AEGIS a question for a playful 8-ball answer.",
    )
    @app_commands.describe(question="A short question.")
    async def eightball(self, ctx: commands.Context, *, question: str) -> None:
        if not question.strip() or len(question) > 500:
            await ctx.send(
                "Ask a question of 1–500 characters.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        answer = random.choice(EIGHT_BALL_ANSWERS)
        await ctx.send(
            f"**{question.strip()}**\n{answer}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.hybrid_command(
        name="choose",
        description="Choose one item from a comma-separated list.",
    )
    @app_commands.describe(options="Provide 2–20 options separated by commas.")
    async def choose(self, ctx: commands.Context, *, options: str) -> None:
        choices = [item.strip() for item in options.split(",") if item.strip()]
        if len(choices) < 2 or len(choices) > 20:
            await ctx.send(
                "Provide between 2 and 20 comma-separated options.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return
        selected = random.choice(choices)
        await ctx.send(
            f"I choose: **{selected[:300]}**",
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog())
