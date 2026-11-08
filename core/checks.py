"""Discord command checks for moderation permissions."""

from __future__ import annotations

from discord.ext import commands


def has_guild_permission(permission: str):
    """Allow a guild owner or a member with the named guild permission."""

    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if ctx.author.id == ctx.guild.owner_id:
            return True
        permissions = getattr(ctx.author, "guild_permissions", None)
        if not bool(getattr(permissions, permission, False)):
            raise commands.MissingPermissions([permission])
        return True

    return commands.check(predicate)
