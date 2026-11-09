"""Lightweight, self-contained entertainment commands."""

from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands


_EIGHT_BALL_ANSWERS = (
    "It is certain.",
    "Signs point to yes.",
    "Most likely.",
    "Ask again later.",
    "The answer is unclear.",
    "Don't count on it.",
    "Very doubtful.",
    "Outlook is good.",
)
_JOKES = (
    "Why did the computer get cold? It left its Windows open.",
    "I told my code a joke. It returned an exception.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "A SQL query walks into a bar, walks up to two tables, and asks: “Can I join you?”",
)


def parse_choice_options(value: str) -> list[str]:
    """Parse a small list of options separated by vertical bars."""
    options = [part.strip() for part in value.split("|") if part.strip()]
    if not 2 <= len(options) <= 25:
        raise ValueError("Provide 2–25 choices separated with `|`.")
    if any(len(option) > 100 for option in options):
        raise ValueError("Each choice must be 100 characters or fewer.")
    return options


def roll_dice(count: int = 1, sides: int = 6) -> list[int]:
    """Roll a bounded number of fair, ordinary dice."""
    if not 1 <= count <= 20:
        raise ValueError("Roll between 1 and 20 dice at a time.")
    if not 2 <= sides <= 1000:
        raise ValueError("Each die must have 2–1000 sides.")
    return [random.randint(1, sides) for _ in range(count)]


def _safe_mentions() -> discord.AllowedMentions:
    return discord.AllowedMentions.none()


class FunCog(commands.Cog):
    """A small set of deterministic-format, server-safe entertainment tools."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="eightball",
        aliases=("8ball",),
        description="Ask the classic 8-ball a question.",
    )
    @app_commands.describe(question="Your question.")
    async def eightball(self, ctx: commands.Context, *, question: str) -> None:
        question = question.strip()
        if not question:
            await ctx.send("Ask a question first.", ephemeral=ctx.interaction is not None)
            return
        await ctx.send(
            f"🎱 **Question:** {question[:300]}\n**Answer:** {random.choice(_EIGHT_BALL_ANSWERS)}",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_safe_mentions(),
        )

    @commands.hybrid_command(name="coinflip", description="Flip a virtual coin.")
    async def coinflip(self, ctx: commands.Context) -> None:
        await ctx.send(
            f"🪙 {random.choice(('Heads', 'Tails'))}.",
            ephemeral=ctx.interaction is not None,
        )

    @commands.hybrid_command(name="dice", description="Roll one or more dice.")
    @app_commands.describe(count="Number of dice, from 1 to 20.", sides="Sides per die, from 2 to 1000.")
    async def dice(
        self,
        ctx: commands.Context,
        count: int = 1,
        sides: int = 6,
    ) -> None:
        try:
            rolls = roll_dice(count, sides)
        except ValueError as exc:
            await ctx.send(str(exc), ephemeral=ctx.interaction is not None)
            return
        await ctx.send(
            f"🎲 Rolls: {', '.join(map(str, rolls))} • Total: **{sum(rolls)}**",
            ephemeral=ctx.interaction is not None,
        )

    @commands.hybrid_command(name="choose", description="Pick one option from a list.")
    @app_commands.describe(options="Separate 2–25 options with |, for example tea | coffee.")
    async def choose(self, ctx: commands.Context, *, options: str) -> None:
        try:
            items = parse_choice_options(options)
        except ValueError as exc:
            await ctx.send(str(exc), ephemeral=ctx.interaction is not None)
            return
        await ctx.send(
            f"🎯 I choose: **{random.choice(items)}**",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_safe_mentions(),
        )

    @commands.hybrid_command(name="rate", description="Give something a playful score.")
    @app_commands.describe(thing="The thing you want rated.")
    async def rate(self, ctx: commands.Context, *, thing: str) -> None:
        thing = thing.strip()
        if not thing:
            await ctx.send("Tell me what to rate.", ephemeral=ctx.interaction is not None)
            return
        await ctx.send(
            f"📊 **{thing[:250]}** gets **{random.randint(0, 100)}/100**.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_safe_mentions(),
        )

    @commands.hybrid_command(name="ship", description="Generate a just-for-fun compatibility score.")
    @app_commands.describe(first="First person.", second="Second person.")
    async def ship(
        self,
        ctx: commands.Context,
        first: discord.User,
        second: discord.User,
    ) -> None:
        if first.id == second.id:
            await ctx.send(
                "Pick two different people for a ship score.",
                ephemeral=ctx.interaction is not None,
            )
            return
        score = random.randint(0, 100)
        names = (
            getattr(first, "display_name", first.name),
            getattr(second, "display_name", second.name),
        )
        await ctx.send(
            f"💞 **{names[0]} + {names[1]}**: **{score}%** compatibility — just for fun.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_safe_mentions(),
        )

    @commands.hybrid_command(name="joke", description="Get a short built-in joke.")
    async def joke(self, ctx: commands.Context) -> None:
        await ctx.send(
            random.choice(_JOKES),
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_safe_mentions(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog(bot))
