"""Persistent reminders and practical, safe utility commands."""

from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.utility import calculate, parse_duration_seconds
from database.repositories.community import CommunityRepository


logger = logging.getLogger(__name__)


def _repository(bot: commands.Bot) -> CommunityRepository:
    repository = getattr(bot, "community_repository", None)
    if not isinstance(repository, CommunityRepository):
        raise RuntimeError("The community database is not initialized.")
    return repository


def _no_mentions() -> discord.AllowedMentions:
    return discord.AllowedMentions.none()


class UtilityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.repository = _repository(bot)

    async def cog_unload(self) -> None:
        self.reminder_worker.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if not self.reminder_worker.is_running():
            self.reminder_worker.start()

    @tasks.loop(seconds=15)
    async def reminder_worker(self) -> None:
        try:
            reminders = await self.repository.claim_due_reminders()
        except Exception:
            logger.exception("Could not claim due AEGIS reminders.")
            return
        for reminder in reminders:
            try:
                user = self.bot.get_user(reminder.user_id)
                if user is None:
                    user = await self.bot.fetch_user(reminder.user_id)
                await user.send(
                    f"⏰ Reminder: {reminder.message}",
                    allowed_mentions=_no_mentions(),
                )
            except discord.HTTPException:
                logger.warning(
                    "Reminder %s could not be delivered to user %s.",
                    reminder.reminder_id,
                    reminder.user_id,
                )
                try:
                    await self.repository.fail_reminder(reminder.reminder_id)
                except Exception:
                    logger.exception("Could not mark reminder %s as failed.", reminder.reminder_id)
            else:
                try:
                    await self.repository.complete_reminder(reminder.reminder_id)
                except Exception:
                    logger.exception("Could not complete reminder %s.", reminder.reminder_id)

    @commands.hybrid_command(
        name="remind",
        description="Schedule a private reminder.",
    )
    @app_commands.describe(
        when="Duration such as 10m, 2h, or 1d.",
        message="The reminder text, sent privately to you.",
    )
    async def remind(
        self,
        ctx: commands.Context,
        when: str,
        *,
        message: str,
    ) -> None:
        try:
            seconds = parse_duration_seconds(when)
            due_at = discord.utils.utcnow() + timedelta(seconds=seconds)
            reminder_id = await self.repository.create_reminder(
                user_id=ctx.author.id,
                message=message,
                remind_at=due_at,
            )
        except ValueError as exc:
            await ctx.send(str(exc), ephemeral=ctx.interaction is not None)
            return
        await ctx.send(
            f"Reminder `#{reminder_id}` saved. I’ll DM you <t:{int(due_at.timestamp())}:R>.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_no_mentions(),
        )

    @commands.hybrid_command(
        name="reminders",
        description="List your upcoming reminders.",
    )
    async def reminders(self, ctx: commands.Context) -> None:
        records = await self.repository.list_reminders(user_id=ctx.author.id)
        if not records:
            await ctx.send(
                "You have no pending or undelivered reminders.",
                ephemeral=ctx.interaction is not None,
            )
            return
        lines = [
            f"`#{record.reminder_id}` • <t:{int(discord.utils.parse_time(record.remind_at).timestamp())}:R>"
            f" — {record.message[:120]}"
            + (" *(delivery failed)*" if record.status == "failed" else "")
            for record in records
        ]
        await ctx.send(
            "\n".join(lines),
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_no_mentions(),
        )

    @commands.hybrid_command(
        name="cancelreminder",
        description="Cancel one of your reminders by its ID.",
    )
    @app_commands.describe(reminder_id="The ID shown by /reminders.")
    async def cancelreminder(
        self,
        ctx: commands.Context,
        reminder_id: int,
    ) -> None:
        removed = await self.repository.cancel_reminder(
            reminder_id=reminder_id,
            user_id=ctx.author.id,
        )
        await ctx.send(
            "Reminder cancelled." if removed else "That reminder was not found.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_no_mentions(),
        )

    @commands.hybrid_group(
        name="prefix",
        description="View or manage this server's command prefix.",
        invoke_without_command=True,
    )
    async def prefix(self, ctx: commands.Context) -> None:
        guild_id = ctx.guild.id if ctx.guild is not None else None
        getter = getattr(self.bot, "get_guild_prefix", None)
        prefix = (
            await getter(guild_id)
            if callable(getter)
            else str(getattr(self.bot, "default_prefix", ""))
        )
        mention = self.bot.user.mention if self.bot.user is not None else "mention me"
        await ctx.send(
            f"Prefix here: `{prefix}`. You can also mention {mention} before a command. "
            "Use `prefix set <new-prefix>` to change it.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_no_mentions(),
        )

    @prefix.command(name="set", description="Set this server's command prefix.")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @app_commands.describe(value="A 1–16 character prefix, with no spaces.")
    async def prefix_set(self, ctx: commands.Context, value: str) -> None:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        try:
            prefix = await self.repository.set_guild_prefix(
                guild_id=ctx.guild.id,
                prefix=value,
            )
        except ValueError as exc:
            await ctx.send(str(exc), ephemeral=ctx.interaction is not None)
            return
        await ctx.send(
            f"This server’s prefix is now `{prefix}`. Mention-only prefix replies still work.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_no_mentions(),
        )

    @commands.hybrid_command(
        name="mentionprefix",
        description="Show how to call AEGIS with a bot mention.",
    )
    async def mentionprefix(self, ctx: commands.Context) -> None:
        mention = self.bot.user.mention if self.bot.user is not None else "mention me"
        await ctx.send(
            f"Use {mention} followed by a command, or mention me alone to see this server’s prefix.",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_no_mentions(),
        )

    @commands.hybrid_command(
        name="calculate",
        aliases=("calc",),
        description="Evaluate basic arithmetic safely.",
    )
    @app_commands.describe(expression="Numbers with +, -, *, /, //, %, and bounded powers.")
    async def calculate(
        self,
        ctx: commands.Context,
        *,
        expression: str,
    ) -> None:
        try:
            result = calculate(expression)
        except ValueError as exc:
            await ctx.send(str(exc), ephemeral=ctx.interaction is not None)
            return
        await ctx.send(
            f"`{expression}` = `{result}`",
            ephemeral=ctx.interaction is not None,
            allowed_mentions=_no_mentions(),
        )

    @commands.hybrid_command(name="poll", description="Create a yes/no poll.")
    @app_commands.describe(question="The question people will vote on.")
    async def poll(self, ctx: commands.Context, *, question: str) -> None:
        question = question.strip()
        if not question or len(question) > 800:
            await ctx.send(
                "A poll question must contain 1–800 characters.",
                ephemeral=ctx.interaction is not None,
            )
            return
        embed = discord.Embed(
            title="📊 Poll",
            description=question,
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Vote", value="✅ Yes  ❌ No", inline=False)
        message = await ctx.send(embed=embed, allowed_mentions=_no_mentions())
        if message is None:
            return
        try:
            await message.add_reaction("✅")
            await message.add_reaction("❌")
        except discord.HTTPException:
            logger.warning("Poll reactions could not be added in channel %s.", ctx.channel.id)

    @commands.hybrid_command(
        name="embed",
        description="Send a simple AEGIS-formatted embed.",
    )
    @commands.has_guild_permissions(manage_messages=True)
    @app_commands.describe(
        title="A short title for the embed.",
        description="The embed text.",
    )
    async def embed(
        self,
        ctx: commands.Context,
        title: str,
        *,
        description: str,
    ) -> None:
        if len(title) > 256 or not description.strip() or len(description) > 4000:
            await ctx.send(
                "The title must be at most 256 characters and the description 1–4000.",
                ephemeral=ctx.interaction is not None,
            )
            return
        embed = discord.Embed(
            title=title.strip(),
            description=description.strip(),
            color=discord.Color.blurple(),
        )
        await ctx.send(embed=embed, allowed_mentions=_no_mentions())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
