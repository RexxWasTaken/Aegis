"""Reaction-role panel embed matching the supplied Sapphire reference."""

from __future__ import annotations

from collections.abc import Sequence

import discord

from database.repositories.community import ReactionRoleMapping


REACTION_ROLE_TITLE = "React to this message to assign yourself roles"


def reaction_role_panel_embed(
    mappings: Sequence[ReactionRoleMapping],
) -> discord.Embed:
    rows = [f"{mapping.emoji}  —  <@&{mapping.role_id}>" for mapping in mappings]
    description = "\n".join(rows) if rows else "Add emoji-role mappings to this panel."
    return discord.Embed(title=REACTION_ROLE_TITLE, description=description)
