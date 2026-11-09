"""Environment-backed, guild-scoped moderation configuration."""

from __future__ import annotations

import json
import os
from urllib.parse import urlsplit


JAIL_ROLE_IDS_ENV = "AEGIS_JAIL_ROLE_IDS"
DEFAULT_PREFIX_ENV = "AEGIS_PREFIX"
OWNER_ID_ENV = "OWNER_ID"


def get_default_prefix() -> str:
    """Return the configured default prefix, rejecting ambiguous values."""
    prefix = os.environ.get(DEFAULT_PREFIX_ENV, "a!").strip()
    if not prefix or len(prefix) > 16 or any(character.isspace() for character in prefix):
        raise ValueError(f"{DEFAULT_PREFIX_ENV} must be 1–16 non-whitespace characters.")
    if prefix.startswith("<@"):
        raise ValueError(f"{DEFAULT_PREFIX_ENV} cannot look like a Discord mention.")
    return prefix


def get_owner_id() -> int | None:
    """Read the single bot owner from the environment; unset means no owner access."""
    raw = os.environ.get(OWNER_ID_ENV, "").strip()
    if not raw:
        return None
    if not raw.isdecimal():
        raise ValueError(f"{OWNER_ID_ENV} must be a positive Discord user ID.")
    owner_id = int(raw)
    if owner_id <= 0 or owner_id > 9_223_372_036_854_775_807:
        raise ValueError(f"{OWNER_ID_ENV} must be a positive Discord user ID.")
    return owner_id


def _get_optional_https_url(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{name} must be an HTTPS URL or left blank.")
    return value


def get_support_url() -> str | None:
    """Return the configured AEGIS support URL, if one was supplied."""
    return _get_optional_https_url("AEGIS_SUPPORT_URL")


def get_invite_url() -> str | None:
    """Return the configured AEGIS invite URL, if one was supplied."""
    return _get_optional_https_url("AEGIS_INVITE_URL")


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
