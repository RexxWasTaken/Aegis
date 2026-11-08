"""Prefix and slash Help command backed by the registered command tree."""

from __future__ import annotations

import discord
from discord.ext import commands

from core.help_view import HelpView


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="help", description="Browse AEGIS commands by category.")
    async def help(self, ctx: commands.Context) -> None:
        """Open the interactive AEGIS Help center."""
        view = HelpView(self.bot, ctx.author.id)
        embed, _ = view._page_data()
        try:
            if ctx.interaction is not None:
                message = await ctx.send(embed=embed, view=view, ephemeral=True)
            else:
                message = await ctx.send(embed=embed, view=view)
        except discord.HTTPException:
            message_text = (
                "The Help menu could not be displayed. Check access to the AEGIS "
                "Ticket and Giveaway custom emojis; no Unicode replacement is used."
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
