"""Environment-backed, guild-scoped moderation configuration."""

from __future__ import annotations

import json
import os


JAIL_ROLE_IDS_ENV = "AEGIS_JAIL_ROLE_IDS"


def get_jail_role_id(guild_id: int) -> int | None:
    """Read the configured jail role from a JSON guild-ID-to-role-ID mapping."""
    raw = os.environ.get(JAIL_ROLE_IDS_ENV, "").strip()
    if not raw:
        return None
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{JAIL_ROLE_IDS_ENV} must be a JSON object mapping guild IDs to role IDs."
        ) from exc
    if not isinstance(mapping, dict):
        raise ValueError(
            f"{JAIL_ROLE_IDS_ENV} must be a JSON object mapping guild IDs to role IDs."
        )
    value = mapping.get(str(guild_id))
    if value is None:
        return None
    try:
        role_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"The configured jail role for server {guild_id} must be a positive integer."
        ) from exc
    if role_id <= 0:
        raise ValueError(
            f"The configured jail role for server {guild_id} must be a positive integer."
        )
    return role_id
