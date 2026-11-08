"""Guild-configured jail commands with persistent role restoration."""

from __future__ import annotations

import discord
from discord.ext import commands

from core.checks import has_guild_permission
from core.configuration import JAIL_ROLE_IDS_ENV, get_jail_role_id
from core.permissions import (
    ModerationTargetError,
    validate_role_management_target,
)
from embeds.moderation import success_embed
from services.moderation_service import (
    ModerationServiceError,
    normalize_reason,
)


def _role_is_default(role: discord.Role, guild: discord.Guild) -> bool:
    checker = getattr(role, "is_default", None)
    return bool(checker()) if callable(checker) else role.id == guild.id


def _role_is_assignable(role: discord.Role, bot_member: discord.Member) -> bool:
    checker = getattr(role, "is_assignable", None)
    if callable(checker):
        return bool(checker())
    if checker is not None:
        return bool(checker)
    return (
        not bool(getattr(role, "managed", False))
        and int(getattr(role, "position", 0))
        < int(getattr(getattr(bot_member, "top_role", None), "position", 0))
    )


def _role_has_administrator(role: discord.Role) -> bool:
    return bool(getattr(getattr(role, "permissions", None), "administrator", False))


class JailModerationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _repository(self):
        repository = getattr(self.bot, "moderation_repository", None)
        if repository is None:
            service = getattr(self.bot, "moderation_service", None)
            repository = getattr(service, "repository", None)
        if repository is None:
            raise RuntimeError("The moderation repository is not initialized.")
        return repository

    async def _bot_member(self, guild: discord.Guild) -> discord.Member:
        if guild.me is not None:
            return guild.me
        if self.bot.user is None:
            raise RuntimeError("The bot user is not available yet.")
        return await guild.fetch_member(self.bot.user.id)

    def _configured_jail_role(
        self, guild: discord.Guild, moderator: discord.Member, bot_member: discord.Member
    ) -> discord.Role:
        try:
            role_id = get_jail_role_id(guild.id)
        except ValueError as exc:
            raise ModerationServiceError(str(exc)) from exc
        if role_id is None:
            raise ModerationServiceError(
                f"No jail role is configured for this server. Set {JAIL_ROLE_IDS_ENV} "
                "to a JSON mapping from server ID to role ID."
            )
        role = guild.get_role(role_id)
        if role is None:
            raise ModerationServiceError(
                "The configured jail role no longer exists in this server."
            )
        if (
            _role_is_default(role, guild)
            or bool(getattr(role, "managed", False))
            or _role_has_administrator(role)
            or not _role_is_assignable(role, bot_member)
        ):
            raise ModerationTargetError(
                "The configured jail role must be unmanaged, non-administrator, "
                "and below the bot's highest role."
            )
        if (
            moderator.id != guild.owner_id
            and int(getattr(role, "position", 0))
            >= int(getattr(getattr(moderator, "top_role", None), "position", 0))
        ):
            raise ModerationTargetError(
                "The configured jail role must be below your highest role."
            )
        return role

    @commands.command(name="jail")
    @commands.guild_only()
    @has_guild_permission("manage_roles")
    async def jail(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Assign the configured jail role and save restorable roles."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        guild = ctx.guild
        bot_member = await self._bot_member(guild)
        validate_role_management_target(
            guild, target, ctx.author, bot_member, action="jail"
        )
        jail_role = self._configured_jail_role(guild, ctx.author, bot_member)
        target_roles = list(getattr(target, "roles", ()))
        if any(role.id == jail_role.id for role in target_roles):
            raise ModerationServiceError(
                "The member already has the configured jail role."
            )
        if any(_role_has_administrator(role) for role in target_roles):
            raise ModerationTargetError(
                "A member with an administrator role cannot be jailed safely."
            )
        normalized_reason = normalize_reason(reason)
        saved_role_ids = [
            role.id
            for role in target_roles
            if not _role_is_default(role, guild) and role.id != jail_role.id
        ]
        repository = self._repository()
        inserted = await repository.save_jail_snapshot(
            guild_id=guild.id,
            member_id=target.id,
            jail_role_id=jail_role.id,
            previous_role_ids=saved_role_ids,
        )
        if not inserted:
            raise ModerationServiceError(
                "This member already has saved jail state; use unjail before retrying."
            )

        try:
            await target.add_roles(
                jail_role,
                reason=f"Jailed by moderator {ctx.author.id}: {normalized_reason}"[:512],
            )
        except Exception:
            await repository.delete_jail_snapshot(
                guild_id=guild.id, member_id=target.id
            )
            raise

        removable_roles = [
            role
            for role in target_roles
            if not _role_is_default(role, guild)
            and role.id != jail_role.id
            and _role_is_assignable(role, bot_member)
            and not bool(getattr(role, "managed", False))
        ]
        if removable_roles:
            try:
                await target.remove_roles(
                    *removable_roles,
                    reason=f"Jailed by moderator {ctx.author.id}"[:512],
                )
            except Exception as exc:
                try:
                    await target.remove_roles(
                        jail_role,
                        reason="Rolling back incomplete jail role cleanup",
                    )
                except Exception as rollback_error:
                    raise ModerationServiceError(
                        "The jail role was applied but role cleanup failed. "
                        "Use unjail to restore the saved roles safely."
                    ) from rollback_error
                await repository.delete_jail_snapshot(
                    guild_id=guild.id, member_id=target.id
                )
                raise ModerationServiceError(
                    "Role cleanup failed; the jail role was rolled back."
                ) from exc

        await ctx.send(
            embed=success_embed(
                "jail",
                target=target,
                reason=normalized_reason,
                guild=guild,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="unjail")
    @commands.guild_only()
    @has_guild_permission("manage_roles")
    async def unjail(
        self,
        ctx: commands.Context,
        target: discord.Member,
        *,
        reason: str = "No reason provided.",
    ) -> None:
        """Restore saved assignable roles, then remove the configured jail role."""
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        guild = ctx.guild
        bot_member = await self._bot_member(guild)
        validate_role_management_target(
            guild, target, ctx.author, bot_member, action="unjail"
        )
        repository = self._repository()
        snapshot = await repository.get_jail_snapshot(
            guild_id=guild.id, member_id=target.id
        )
        if snapshot is None:
            raise ModerationServiceError(
                "No saved role state exists for this member; no roles were changed."
            )
        normalized_reason = normalize_reason(reason)
        current_role_ids = {role.id for role in getattr(target, "roles", ())}
        roles_to_restore: list[discord.Role] = []
        skipped = 0
        for role_id in snapshot.previous_role_ids:
            role = guild.get_role(role_id)
            if role is None:
                skipped += 1
            elif role_id not in current_role_ids and (
                _role_is_default(role, guild)
                or bool(getattr(role, "managed", False))
                or not _role_is_assignable(role, bot_member)
            ):
                skipped += 1
            elif role_id not in current_role_ids:
                roles_to_restore.append(role)

        restored = 0
        failed_roles: list[discord.Role] = []
        if roles_to_restore:
            try:
                await target.add_roles(
                    *roles_to_restore,
                    reason=f"Unjailed by moderator {ctx.author.id}: {normalized_reason}"[:512],
                )
                restored = len(roles_to_restore)
            except discord.HTTPException:
                for role in roles_to_restore:
                    try:
                        await target.add_roles(
                            role,
                            reason=f"Unjailed by moderator {ctx.author.id}"[:512],
                        )
                        restored += 1
                    except discord.HTTPException:
                        failed_roles.append(role)

        if failed_roles:
            raise ModerationServiceError(
                f"Role restoration is incomplete: restored {restored}; "
                f"{len(failed_roles)} role(s) could not be restored. The jail state "
                "is retained; fix permissions and run unjail again."
            )

        jail_role = guild.get_role(snapshot.jail_role_id)
        if jail_role is not None and snapshot.jail_role_id in current_role_ids:
            if not _role_is_assignable(jail_role, bot_member):
                raise ModerationServiceError(
                    "The jail role is no longer assignable; role restoration is saved "
                    "but the jail role could not be removed."
                )
            try:
                await target.remove_roles(
                    jail_role,
                    reason=f"Unjailed by moderator {ctx.author.id}: {normalized_reason}"[:512],
                )
            except discord.HTTPException as exc:
                raise ModerationServiceError(
                    "Saved roles were restored, but the jail role could not be removed. "
                    "The saved state is retained; run unjail again after fixing permissions."
                ) from exc

        await repository.delete_jail_snapshot(guild_id=guild.id, member_id=target.id)
        await ctx.send(
            embed=success_embed(
                "unjail",
                target=target,
                restored_count=restored,
                skipped_count=skipped,
                guild=guild,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(JailModerationCog(bot))
