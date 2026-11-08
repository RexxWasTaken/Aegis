"""Prefix and slash Help command backed by the registered command tree."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from core.emoji_manager import emoji_markup
from core.help_view import HelpView, find_command, send_command_details
from embeds.help import HELP_COLOR


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(
        name="help",
        description="Browse registered AEGIS commands or inspect one command.",
    )
    @app_commands.describe(command="A registered command name or prefix alias.")
    async def help(self, ctx: commands.Context, *, command: str | None = None) -> None:
        """Open Help or show details for a registered command or alias."""
        if command:
            info = find_command(self.bot, command)
            if info is None:
                embed = discord.Embed(
                    title=f"{emoji_markup('error')} Command not found",
                    description="That command or alias is not registered.",
                    color=HELP_COLOR,
                )
                if ctx.interaction is not None:
                    await ctx.send(embed=embed, ephemeral=True)
                else:
                    await ctx.send(embed=embed)
                return
            await send_command_details(ctx, info)
            return

        view = HelpView(self.bot, ctx.author.id)
        embed, _ = view._page_data()
        try:
            if ctx.interaction is not None:
                message = await ctx.send(embed=embed, view=view, ephemeral=True)
            else:
                message = await ctx.send(embed=embed, view=view)
        except discord.HTTPException:
            message_text = (
                f"{emoji_markup('error')} The Help menu could not be displayed. "
                "Check access to the configured custom emojis and try again."
            )
            if ctx.interaction is None:
                await ctx.send(message_text)
            elif ctx.interaction.response.is_done():
                await ctx.interaction.followup.send(message_text, ephemeral=True)
            else:
                await ctx.interaction.response.send_message(message_text, ephemeral=True)
            return
        view.message = message


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
