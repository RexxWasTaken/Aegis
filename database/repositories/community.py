"""SQLite persistence for ticket and reaction-giveaway community features."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class TicketConfig:
    guild_id: int
    staff_role_id: int
    category_id: int | None
    log_channel_id: int | None


@dataclass(frozen=True)
class TicketRecord:
    ticket_id: int
    guild_id: int
    channel_id: int
    creator_id: int
    category: str
    status: str
    claimed_by: int | None
    created_at: str
    closed_at: str | None


@dataclass(frozen=True)
class GiveawayRecord:
    message_id: int
    guild_id: int
    channel_id: int
    host_id: int
    prize: str
    winner_count: int
    ends_at: str
    status: str
    paused_seconds: int | None
    winners: tuple[int, ...]
    created_at: str


@dataclass(frozen=True)
class WelcomeConfig:
    guild_id: int
    welcome_channel_id: int | None
    welcome_message: str | None
    welcome_enabled: bool
    goodbye_channel_id: int | None
    goodbye_message: str | None
    goodbye_enabled: bool


@dataclass(frozen=True)
class ReactionRolePanel:
    message_id: int
    guild_id: int
    channel_id: int
    created_by: int


@dataclass(frozen=True)
class ReactionRoleMapping:
    message_id: int
    guild_id: int
    emoji_key: str
    emoji: str
    role_id: int


@dataclass(frozen=True)
class LoggingConfig:
    guild_id: int
    channel_id: int
    enabled: bool
    enabled_events: tuple[str, ...]
    ignored_channels: tuple[int, ...] = ()
    ignored_users: tuple[int, ...] = ()
    ignored_roles: tuple[int, ...] = ()


class CommunityRepository:
    """Store community state in the existing AEGIS SQLite database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            if self._db is not None:
                return
            if self.db_path != ":memory:":
                Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA foreign_keys = ON")
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_configs (
                    guild_id INTEGER PRIMARY KEY,
                    staff_role_id INTEGER NOT NULL,
                    category_id INTEGER,
                    log_channel_id INTEGER
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL UNIQUE,
                    creator_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    claimed_by INTEGER,
                    created_at TEXT NOT NULL,
                    closed_at TEXT
                )
                """
            )
            await self._db.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tickets_one_open_per_creator
                ON tickets(guild_id, creator_id) WHERE status = 'open'
                """
            )
            await self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tickets_guild_status
                ON tickets(guild_id, status, ticket_id)
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    actor_id INTEGER NOT NULL,
                    event TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_transcripts (
                    ticket_id INTEGER PRIMARY KEY,
                    transcript BLOB NOT NULL,
                    saved_at TEXT NOT NULL
                )
                """
            )
            await self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ticket_events_ticket
                ON ticket_events(ticket_id, event_id)
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS giveaways (
                    message_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    prize TEXT NOT NULL,
                    winner_count INTEGER NOT NULL CHECK (winner_count > 0),
                    ends_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    paused_seconds INTEGER,
                    winners_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                )
                """
            )
            await self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_giveaways_due
                ON giveaways(status, ends_at)
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS welcome_configs (
                    guild_id INTEGER PRIMARY KEY,
                    welcome_channel_id INTEGER,
                    welcome_message TEXT,
                    welcome_enabled INTEGER NOT NULL DEFAULT 0,
                    goodbye_channel_id INTEGER,
                    goodbye_message TEXT,
                    goodbye_enabled INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS reaction_role_panels (
                    message_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    created_by INTEGER NOT NULL
                )
                """
            )
            await self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_reaction_role_panels_guild
                ON reaction_role_panels(guild_id, message_id)
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS reaction_role_mappings (
                    message_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    emoji_key TEXT NOT NULL,
                    emoji TEXT NOT NULL,
                    role_id INTEGER NOT NULL,
                    PRIMARY KEY(message_id, emoji_key),
                    FOREIGN KEY(message_id) REFERENCES reaction_role_panels(message_id)
                        ON DELETE CASCADE
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS logging_configs (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    events_json TEXT NOT NULL DEFAULT '[]'
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS logging_ignored (
                    guild_id INTEGER NOT NULL,
                    target_type TEXT NOT NULL
                        CHECK(target_type IN ('channel', 'user', 'role')),
                    target_id INTEGER NOT NULL,
                    PRIMARY KEY(guild_id, target_type, target_id)
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS guild_prefixes (
                    guild_id INTEGER PRIMARY KEY,
                    prefix TEXT NOT NULL
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS no_prefix_users (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await self._db.commit()

    def _connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("CommunityRepository.initialize() must be called first.")
        return self._db

    async def set_ticket_config(
        self,
        *,
        guild_id: int,
        staff_role_id: int,
        category_id: int | None,
        log_channel_id: int | None,
    ) -> TicketConfig:
        async with self._lock:
            await self._connection().execute(
                """
                INSERT INTO ticket_configs
                    (guild_id, staff_role_id, category_id, log_channel_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    staff_role_id = excluded.staff_role_id,
                    category_id = excluded.category_id,
                    log_channel_id = excluded.log_channel_id
                """,
                (guild_id, staff_role_id, category_id, log_channel_id),
            )
            await self._connection().commit()
        return TicketConfig(guild_id, staff_role_id, category_id, log_channel_id)

    async def get_ticket_config(self, guild_id: int) -> TicketConfig | None:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT * FROM ticket_configs WHERE guild_id = ?", (guild_id,)
            )
            row = await cursor.fetchone()
        return TicketConfig(**dict(row)) if row is not None else None

    async def create_ticket(
        self,
        *,
        guild_id: int,
        channel_id: int,
        creator_id: int,
        category: str,
    ) -> TicketRecord:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            async with self._lock:
                cursor = await self._connection().execute(
                    """
                    INSERT INTO tickets
                        (guild_id, channel_id, creator_id, category, status, created_at)
                    VALUES (?, ?, ?, ?, 'open', ?)
                    """,
                    (guild_id, channel_id, creator_id, category, created_at),
                )
                await self._connection().commit()
                ticket_id = int(cursor.lastrowid)
        except aiosqlite.IntegrityError as exc:
            raise ValueError("This member already has an open ticket.") from exc
        return TicketRecord(
            ticket_id=ticket_id,
            guild_id=guild_id,
            channel_id=channel_id,
            creator_id=creator_id,
            category=category,
            status="open",
            claimed_by=None,
            created_at=created_at,
            closed_at=None,
        )

    async def get_ticket(self, channel_id: int) -> TicketRecord | None:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
            )
            row = await cursor.fetchone()
        return TicketRecord(**dict(row)) if row is not None else None

    async def get_open_ticket(
        self, *, guild_id: int, creator_id: int
    ) -> TicketRecord | None:
        async with self._lock:
            cursor = await self._connection().execute(
                """
                SELECT * FROM tickets
                WHERE guild_id = ? AND creator_id = ? AND status = 'open'
                ORDER BY ticket_id DESC LIMIT 1
                """,
                (guild_id, creator_id),
            )
            row = await cursor.fetchone()
        return TicketRecord(**dict(row)) if row is not None else None

    async def claim_ticket(
        self, *, channel_id: int, staff_id: int
    ) -> TicketRecord:
        async with self._lock:
            db = self._connection()
            await db.execute(
                """
                UPDATE tickets SET claimed_by = ?
                WHERE channel_id = ? AND status = 'open'
                  AND (claimed_by IS NULL OR claimed_by = ?)
                """,
                (staff_id, channel_id, staff_id),
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise LookupError("This channel is not a ticket.")
        ticket = TicketRecord(**dict(row))
        if ticket.status != "open":
            raise ValueError("Only open tickets can be claimed.")
        if ticket.claimed_by != staff_id:
            raise ValueError("This ticket has already been claimed by another staff member.")
        return ticket

    async def set_ticket_status(
        self, *, channel_id: int, status: str, closed_at: str | None
    ) -> TicketRecord:
        if status not in {"open", "closed"}:
            raise ValueError("Ticket status must be open or closed.")
        async with self._lock:
            db = self._connection()
            try:
                await db.execute(
                    "UPDATE tickets SET status = ?, closed_at = ? WHERE channel_id = ?",
                    (status, closed_at, channel_id),
                )
                await db.commit()
            except aiosqlite.IntegrityError as exc:
                await db.rollback()
                raise ValueError(
                    "This member already has another open ticket."
                ) from exc
            cursor = await db.execute(
                "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise LookupError("This channel is not a ticket.")
        return TicketRecord(**dict(row))

    async def log_ticket_event(
        self,
        *,
        ticket_id: int,
        guild_id: int,
        actor_id: int,
        event: str,
        details: str,
    ) -> None:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with self._lock:
            await self._connection().execute(
                """
                INSERT INTO ticket_events
                    (ticket_id, guild_id, actor_id, event, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ticket_id, guild_id, actor_id, event, details, created_at),
            )
            await self._connection().commit()

    async def save_ticket_transcript(
        self,
        *,
        ticket_id: int,
        transcript: bytes,
    ) -> None:
        saved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with self._lock:
            await self._connection().execute(
                """
                INSERT INTO ticket_transcripts (ticket_id, transcript, saved_at)
                VALUES (?, ?, ?)
                ON CONFLICT(ticket_id) DO UPDATE SET
                    transcript = excluded.transcript,
                    saved_at = excluded.saved_at
                """,
                (ticket_id, transcript, saved_at),
            )
            await self._connection().commit()

    async def get_ticket_transcript(self, ticket_id: int) -> bytes | None:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT transcript FROM ticket_transcripts WHERE ticket_id = ?",
                (ticket_id,),
            )
            row = await cursor.fetchone()
        return bytes(row["transcript"]) if row is not None else None

    async def create_giveaway(
        self,
        *,
        message_id: int,
        guild_id: int,
        channel_id: int,
        host_id: int,
        prize: str,
        winner_count: int,
        ends_at: datetime,
    ) -> GiveawayRecord:
        if winner_count < 1:
            raise ValueError("A giveaway must have at least one winner.")
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        end_value = ends_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        async with self._lock:
            await self._connection().execute(
                """
                INSERT INTO giveaways
                    (message_id, guild_id, channel_id, host_id, prize, winner_count,
                     ends_at, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    message_id,
                    guild_id,
                    channel_id,
                    host_id,
                    prize,
                    winner_count,
                    end_value,
                    created_at,
                ),
            )
            await self._connection().commit()
        return GiveawayRecord(
            message_id=message_id,
            guild_id=guild_id,
            channel_id=channel_id,
            host_id=host_id,
            prize=prize,
            winner_count=winner_count,
            ends_at=end_value,
            status="active",
            paused_seconds=None,
            winners=(),
            created_at=created_at,
        )

    @staticmethod
    def _giveaway_from_row(row: aiosqlite.Row) -> GiveawayRecord:
        values = dict(row)
        try:
            winners = tuple(int(value) for value in json.loads(values.pop("winners_json")))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("The saved giveaway winner list is invalid.") from exc
        return GiveawayRecord(**values, winners=winners)

    async def get_giveaway(self, message_id: int) -> GiveawayRecord | None:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT * FROM giveaways WHERE message_id = ?", (message_id,)
            )
            row = await cursor.fetchone()
        return self._giveaway_from_row(row) if row is not None else None

    async def update_giveaway(
        self,
        *,
        message_id: int,
        status: str,
        ends_at: datetime | None = None,
        paused_seconds: int | None = None,
        winners: tuple[int, ...] | None = None,
    ) -> GiveawayRecord:
        if status not in {"active", "paused", "ended", "cancelled"}:
            raise ValueError("Invalid giveaway status.")
        assignments = ["status = ?"]
        values: list[object] = [status]
        if ends_at is not None:
            assignments.append("ends_at = ?")
            values.append(ends_at.astimezone(timezone.utc).isoformat(timespec="seconds"))
        if paused_seconds is not None or status != "paused":
            assignments.append("paused_seconds = ?")
            values.append(paused_seconds)
        if winners is not None:
            assignments.append("winners_json = ?")
            values.append(json.dumps([int(value) for value in winners]))
        values.append(message_id)
        async with self._lock:
            db = self._connection()
            await db.execute(
                f"UPDATE giveaways SET {', '.join(assignments)} WHERE message_id = ?",
                values,
            )
            await db.commit()
            cursor = await db.execute(
                "SELECT * FROM giveaways WHERE message_id = ?", (message_id,)
            )
            row = await cursor.fetchone()
        if row is None:
            raise LookupError("This giveaway was not found.")
        return self._giveaway_from_row(row)

    async def list_giveaways(
        self,
        *,
        guild_id: int,
        statuses: tuple[str, ...] = ("active", "paused"),
        limit: int = 25,
    ) -> list[GiveawayRecord]:
        if not statuses or limit < 1:
            return []
        placeholders = ",".join("?" for _ in statuses)
        async with self._lock:
            cursor = await self._connection().execute(
                f"""
                SELECT * FROM giveaways
                WHERE guild_id = ? AND status IN ({placeholders})
                ORDER BY ends_at, message_id LIMIT ?
                """,
                (guild_id, *statuses, limit),
            )
            rows = await cursor.fetchall()
        return [self._giveaway_from_row(row) for row in rows]

    async def due_giveaways(
        self, now: datetime | None = None
    ) -> list[GiveawayRecord]:
        cutoff = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(
            timespec="seconds"
        )
        async with self._lock:
            cursor = await self._connection().execute(
                """
                SELECT * FROM giveaways
                WHERE status = 'active' AND ends_at <= ?
                ORDER BY ends_at, message_id
                """,
                (cutoff,),
            )
            rows = await cursor.fetchall()
        return [self._giveaway_from_row(row) for row in rows]

    async def delete_giveaway(self, message_id: int) -> bool:
        async with self._lock:
            cursor = await self._connection().execute(
                "DELETE FROM giveaways WHERE message_id = ?", (message_id,)
            )
            await self._connection().commit()
        return cursor.rowcount == 1

    async def set_welcome_config(
        self,
        *,
        guild_id: int,
        kind: str,
        channel_id: int,
        message: str,
    ) -> WelcomeConfig:
        if kind not in {"welcome", "goodbye"}:
            raise ValueError("Welcome type must be welcome or goodbye.")
        if channel_id <= 0 or not message.strip() or len(message) > 2000:
            raise ValueError("Choose a channel and a message of 1–2000 characters.")
        if kind == "welcome":
            sql = """
                INSERT INTO welcome_configs
                    (guild_id, welcome_channel_id, welcome_message, welcome_enabled)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id) DO UPDATE SET
                    welcome_channel_id = excluded.welcome_channel_id,
                    welcome_message = excluded.welcome_message,
                    welcome_enabled = 1
            """
        else:
            sql = """
                INSERT INTO welcome_configs
                    (guild_id, goodbye_channel_id, goodbye_message, goodbye_enabled)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id) DO UPDATE SET
                    goodbye_channel_id = excluded.goodbye_channel_id,
                    goodbye_message = excluded.goodbye_message,
                    goodbye_enabled = 1
            """
        async with self._lock:
            await self._connection().execute(sql, (guild_id, channel_id, message))
            await self._connection().commit()
            cursor = await self._connection().execute(
                "SELECT * FROM welcome_configs WHERE guild_id = ?", (guild_id,)
            )
            row = await cursor.fetchone()
        return self._welcome_config_from_row(row)

    @staticmethod
    def _welcome_config_from_row(row: aiosqlite.Row) -> WelcomeConfig:
        values = dict(row)
        values["welcome_enabled"] = bool(values["welcome_enabled"])
        values["goodbye_enabled"] = bool(values["goodbye_enabled"])
        return WelcomeConfig(**values)

    async def get_welcome_config(self, guild_id: int) -> WelcomeConfig | None:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT * FROM welcome_configs WHERE guild_id = ?", (guild_id,)
            )
            row = await cursor.fetchone()
        return self._welcome_config_from_row(row) if row is not None else None

    async def disable_welcome(self, *, guild_id: int, kind: str) -> bool:
        if kind not in {"welcome", "goodbye"}:
            raise ValueError("Welcome type must be welcome or goodbye.")
        enabled_column = f"{kind}_enabled"
        async with self._lock:
            cursor = await self._connection().execute(
                f"UPDATE welcome_configs SET {enabled_column} = 0 WHERE guild_id = ?",
                (guild_id,),
            )
            await self._connection().commit()
        return cursor.rowcount == 1

    async def create_reaction_role_panel(
        self,
        *,
        message_id: int,
        guild_id: int,
        channel_id: int,
        created_by: int,
    ) -> ReactionRolePanel:
        async with self._lock:
            await self._connection().execute(
                """
                INSERT INTO reaction_role_panels
                    (message_id, guild_id, channel_id, created_by)
                VALUES (?, ?, ?, ?)
                """,
                (message_id, guild_id, channel_id, created_by),
            )
            await self._connection().commit()
        return ReactionRolePanel(message_id, guild_id, channel_id, created_by)

    async def get_reaction_role_panel(
        self, message_id: int
    ) -> ReactionRolePanel | None:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT * FROM reaction_role_panels WHERE message_id = ?",
                (message_id,),
            )
            row = await cursor.fetchone()
        return ReactionRolePanel(**dict(row)) if row is not None else None

    async def list_reaction_role_panels(
        self, guild_id: int | None = None
    ) -> list[ReactionRolePanel]:
        async with self._lock:
            if guild_id is None:
                cursor = await self._connection().execute(
                    "SELECT * FROM reaction_role_panels ORDER BY guild_id, message_id"
                )
            else:
                cursor = await self._connection().execute(
                    """
                    SELECT * FROM reaction_role_panels
                    WHERE guild_id = ? ORDER BY message_id
                    """,
                    (guild_id,),
                )
            rows = await cursor.fetchall()
        return [ReactionRolePanel(**dict(row)) for row in rows]

    async def add_reaction_role_mapping(
        self,
        *,
        message_id: int,
        guild_id: int,
        emoji_key: str,
        emoji: str,
        role_id: int,
    ) -> ReactionRoleMapping:
        try:
            async with self._lock:
                await self._connection().execute(
                    """
                    INSERT INTO reaction_role_mappings
                        (message_id, guild_id, emoji_key, emoji, role_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (message_id, guild_id, emoji_key, emoji, role_id),
                )
                await self._connection().commit()
        except aiosqlite.IntegrityError as exc:
            raise ValueError(
                "That reaction already has a role mapping on this panel."
            ) from exc
        return ReactionRoleMapping(message_id, guild_id, emoji_key, emoji, role_id)

    async def get_reaction_role_mapping(
        self, *, message_id: int, emoji_key: str
    ) -> ReactionRoleMapping | None:
        async with self._lock:
            cursor = await self._connection().execute(
                """
                SELECT * FROM reaction_role_mappings
                WHERE message_id = ? AND emoji_key = ?
                """,
                (message_id, emoji_key),
            )
            row = await cursor.fetchone()
        return ReactionRoleMapping(**dict(row)) if row is not None else None

    async def list_reaction_role_mappings(
        self, message_id: int
    ) -> list[ReactionRoleMapping]:
        async with self._lock:
            cursor = await self._connection().execute(
                """
                SELECT * FROM reaction_role_mappings
                WHERE message_id = ? ORDER BY emoji_key
                """,
                (message_id,),
            )
            rows = await cursor.fetchall()
        return [ReactionRoleMapping(**dict(row)) for row in rows]

    async def remove_reaction_role_mapping(
        self, *, message_id: int, emoji_key: str
    ) -> bool:
        async with self._lock:
            cursor = await self._connection().execute(
                """
                DELETE FROM reaction_role_mappings
                WHERE message_id = ? AND emoji_key = ?
                """,
                (message_id, emoji_key),
            )
            await self._connection().commit()
        return cursor.rowcount == 1

    async def delete_reaction_role_panel(self, message_id: int) -> bool:
        async with self._lock:
            cursor = await self._connection().execute(
                "DELETE FROM reaction_role_panels WHERE message_id = ?",
                (message_id,),
            )
            await self._connection().commit()
        return cursor.rowcount == 1

    async def set_logging_config(
        self,
        *,
        guild_id: int,
        channel_id: int | None = None,
        enabled: bool | None = None,
        enabled_events: tuple[str, ...] | None = None,
    ) -> LoggingConfig:
        async with self._lock:
            db = self._connection()
            cursor = await db.execute(
                "SELECT * FROM logging_configs WHERE guild_id = ?", (guild_id,)
            )
            current = await cursor.fetchone()
            if current is None:
                if channel_id is None:
                    raise LookupError("Set a logging channel before changing settings.")
                events = tuple(sorted(set(enabled_events or ())))
                await db.execute(
                    """
                    INSERT INTO logging_configs (guild_id, channel_id, enabled, events_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        channel_id,
                        int(True if enabled is None else enabled),
                        json.dumps(events),
                    ),
                )
            else:
                new_channel = int(channel_id or current["channel_id"])
                new_enabled = int(
                    bool(current["enabled"]) if enabled is None else enabled
                )
                try:
                    old_events = tuple(json.loads(current["events_json"]))
                except (TypeError, ValueError, json.JSONDecodeError):
                    old_events = ()
                events = tuple(
                    sorted(set(old_events if enabled_events is None else enabled_events))
                )
                await db.execute(
                    """
                    UPDATE logging_configs
                    SET channel_id = ?, enabled = ?, events_json = ?
                    WHERE guild_id = ?
                    """,
                    (new_channel, new_enabled, json.dumps(events), guild_id),
                )
            await db.commit()
        result = await self.get_logging_config(guild_id)
        if result is None:
            raise RuntimeError("Logging settings could not be saved.")
        return result

    async def get_logging_config(self, guild_id: int) -> LoggingConfig | None:
        async with self._lock:
            db = self._connection()
            cursor = await db.execute(
                "SELECT * FROM logging_configs WHERE guild_id = ?", (guild_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            ignore_cursor = await db.execute(
                """
                SELECT target_type, target_id FROM logging_ignored
                WHERE guild_id = ? ORDER BY target_type, target_id
                """,
                (guild_id,),
            )
            ignored_rows = await ignore_cursor.fetchall()
        try:
            events = tuple(sorted(set(json.loads(row["events_json"]))))
        except (TypeError, ValueError, json.JSONDecodeError):
            events = ()
        ignored = {"channel": [], "user": [], "role": []}
        for ignored_row in ignored_rows:
            ignored[str(ignored_row["target_type"])].append(
                int(ignored_row["target_id"])
            )
        return LoggingConfig(
            guild_id=int(row["guild_id"]),
            channel_id=int(row["channel_id"]),
            enabled=bool(row["enabled"]),
            enabled_events=events,
            ignored_channels=tuple(ignored["channel"]),
            ignored_users=tuple(ignored["user"]),
            ignored_roles=tuple(ignored["role"]),
        )

    async def set_logging_event(
        self, *, guild_id: int, event: str, enabled: bool
    ) -> LoggingConfig:
        config = await self.get_logging_config(guild_id)
        if config is None:
            raise LookupError("Configure a logging channel before changing events.")
        events = set(config.enabled_events)
        if enabled:
            events.add(event)
        else:
            events.discard(event)
        return await self.set_logging_config(
            guild_id=guild_id,
            enabled_events=tuple(sorted(events)),
        )

    async def set_logging_ignore(
        self,
        *,
        guild_id: int,
        target_type: str,
        target_id: int,
        ignored: bool,
    ) -> bool:
        if target_type not in {"channel", "user", "role"} or target_id <= 0:
            raise ValueError("Choose a valid channel, user, or role ID.")
        async with self._lock:
            db = self._connection()
            if ignored:
                cursor = await db.execute(
                    """
                    INSERT OR IGNORE INTO logging_ignored
                        (guild_id, target_type, target_id)
                    VALUES (?, ?, ?)
                    """,
                    (guild_id, target_type, target_id),
                )
            else:
                cursor = await db.execute(
                    """
                    DELETE FROM logging_ignored
                    WHERE guild_id = ? AND target_type = ? AND target_id = ?
                    """,
                    (guild_id, target_type, target_id),
                )
            await db.commit()
        return cursor.rowcount == 1

    async def get_guild_prefix(self, guild_id: int, *, default_prefix: str) -> str:
        if guild_id <= 0:
            raise ValueError("A valid server ID is required.")
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT prefix FROM guild_prefixes WHERE guild_id = ?",
                (guild_id,),
            )
            row = await cursor.fetchone()
        return str(row["prefix"]) if row is not None else default_prefix

    async def set_guild_prefix(self, *, guild_id: int, prefix: str) -> str:
        if guild_id <= 0:
            raise ValueError("A valid server ID is required.")
        normalized = prefix.strip()
        if (
            not normalized
            or len(normalized) > 16
            or any(character.isspace() for character in normalized)
            or normalized.startswith("<@")
        ):
            raise ValueError(
                "The prefix must be 1–16 non-whitespace characters and cannot be a mention."
            )
        async with self._lock:
            await self._connection().execute(
                """
                INSERT INTO guild_prefixes (guild_id, prefix)
                VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET prefix = excluded.prefix
                """,
                (guild_id, normalized),
            )
            await self._connection().commit()
        return normalized

    async def add_no_prefix_user(self, *, user_id: int, added_by: int) -> bool:
        self._validate_discord_id(user_id, "user")
        self._validate_discord_id(added_by, "owner")
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with self._lock:
            cursor = await self._connection().execute(
                """
                INSERT OR IGNORE INTO no_prefix_users (user_id, added_by, created_at)
                VALUES (?, ?, ?)
                """,
                (user_id, added_by, created_at),
            )
            await self._connection().commit()
        return cursor.rowcount == 1

    async def remove_no_prefix_user(self, *, user_id: int) -> bool:
        self._validate_discord_id(user_id, "user")
        async with self._lock:
            cursor = await self._connection().execute(
                "DELETE FROM no_prefix_users WHERE user_id = ?",
                (user_id,),
            )
            await self._connection().commit()
        return cursor.rowcount == 1

    async def has_no_prefix_user(self, user_id: int) -> bool:
        self._validate_discord_id(user_id, "user")
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT 1 FROM no_prefix_users WHERE user_id = ?",
                (user_id,),
            )
            return await cursor.fetchone() is not None

    async def list_no_prefix_users(self) -> list[int]:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT user_id FROM no_prefix_users ORDER BY user_id"
            )
            rows = await cursor.fetchall()
        return [int(row["user_id"]) for row in rows]

    @staticmethod
    def _validate_discord_id(value: int, label: str) -> None:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            or value > 9_223_372_036_854_775_807
        ):
            raise ValueError(f"A valid Discord {label} ID is required.")

    async def close(self) -> None:
        async with self._lock:
            if self._db is not None:
                await self._db.close()
                self._db = None
