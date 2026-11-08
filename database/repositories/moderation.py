"""SQLite persistence for moderation cases, using additive safe migrations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


@dataclass(frozen=True)
class ModerationCase:
    case_id: int
    guild_id: int
    target_id: int
    moderator_id: int
    action_type: str
    reason: str
    created_at: str
    expires_at: str | None
    status: str


@dataclass(frozen=True)
class ModerationWarning:
    warning_id: int
    guild_id: int
    target_id: int
    moderator_id: int
    reason: str
    created_at: str


@dataclass(frozen=True)
class WarningStats:
    total_warnings: int
    members_warned: int
    moderators_with_warnings: int


class ModerationRepository:
    """Stores moderation audit cases without resetting existing database data."""

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
                CREATE TABLE IF NOT EXISTS moderation_cases (
                    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
            await self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS moderation_warnings (
                    warning_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor = await self._db.execute("PRAGMA table_info(moderation_cases)")
            columns = {row["name"] for row in await cursor.fetchall()}
            if "status" not in columns:
                await self._db.execute(
                    "ALTER TABLE moderation_cases "
                    "ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'"
                )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_moderation_cases_guild_case "
                "ON moderation_cases(guild_id, case_id)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_moderation_cases_target "
                "ON moderation_cases(guild_id, target_id)"
            )
            await self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_moderation_warnings_target "
                "ON moderation_warnings(guild_id, target_id, warning_id)"
            )
            await self._db.execute(
                """
                UPDATE moderation_cases
                SET status = 'completed'
                WHERE action_type = 'tempban' AND status = 'expiry_pending'
                """
            )
            await self._db.execute("PRAGMA user_version = 2")
            await self._db.commit()

    def _connection(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ModerationRepository.initialize() must be called first.")
        return self._db

    async def create_case(
        self,
        *,
        guild_id: int,
        target_id: int,
        moderator_id: int,
        action_type: str,
        reason: str,
        expires_at: str | None = None,
    ) -> ModerationCase:
        if action_type not in {
            "ban", "unban", "softban", "tempban", "kick", "massban", "masskick",
            "timeout", "untimeout", "mute", "unmute",
            "voicemute", "voiceunmute",
            "deafen", "undeafen", "disconnect", "move",
        }:
            raise ValueError("Unsupported moderation action for this repository method.")
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with self._lock:
            db = self._connection()
            cursor = await db.execute(
                """
                INSERT INTO moderation_cases
                    (guild_id, target_id, moderator_id, action_type, reason,
                     created_at, expires_at, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (guild_id, target_id, moderator_id, action_type, reason, created_at, expires_at),
            )
            await db.commit()
            case_id = int(cursor.lastrowid)
        return ModerationCase(
            case_id=case_id,
            guild_id=guild_id,
            target_id=target_id,
            moderator_id=moderator_id,
            action_type=action_type,
            reason=reason,
            created_at=created_at,
            expires_at=expires_at,
            status="pending",
        )

    async def create_warning(
        self,
        *,
        guild_id: int,
        target_id: int,
        moderator_id: int,
        reason: str,
    ) -> ModerationWarning:
        """Persist a warning with its guild, target, moderator and timestamp."""
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        async with self._lock:
            cursor = await self._connection().execute(
                """
                INSERT INTO moderation_warnings
                    (guild_id, target_id, moderator_id, reason, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, target_id, moderator_id, reason, created_at),
            )
            await self._connection().commit()
            warning_id = int(cursor.lastrowid)
        return ModerationWarning(
            warning_id=warning_id,
            guild_id=guild_id,
            target_id=target_id,
            moderator_id=moderator_id,
            reason=reason,
            created_at=created_at,
        )

    async def list_warnings(
        self, *, guild_id: int, target_id: int
    ) -> list[ModerationWarning]:
        """Return one member's warnings in this guild, newest first."""
        async with self._lock:
            cursor = await self._connection().execute(
                """
                SELECT warning_id, guild_id, target_id, moderator_id, reason, created_at
                FROM moderation_warnings
                WHERE guild_id = ? AND target_id = ?
                ORDER BY warning_id DESC
                """,
                (guild_id, target_id),
            )
            rows = await cursor.fetchall()
        return [ModerationWarning(**dict(row)) for row in rows]

    async def list_warning_page(
        self,
        *,
        guild_id: int,
        limit: int,
        offset: int,
        target_id: int | None = None,
    ) -> tuple[list[ModerationWarning], int]:
        """Return one bounded warning page and its total, scoped to a guild."""
        if not 1 <= limit <= 25 or offset < 0:
            raise ValueError("Warning page bounds are invalid.")
        where = "guild_id = ?"
        parameters: list[int] = [guild_id]
        if target_id is not None:
            where += " AND target_id = ?"
            parameters.append(target_id)
        async with self._lock:
            db = self._connection()
            count_cursor = await db.execute(
                f"SELECT COUNT(*) AS total FROM moderation_warnings WHERE {where}",
                parameters,
            )
            total = int((await count_cursor.fetchone())["total"])
            cursor = await db.execute(
                f"""
                SELECT warning_id, guild_id, target_id, moderator_id, reason, created_at
                FROM moderation_warnings
                WHERE {where}
                ORDER BY warning_id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            )
            rows = await cursor.fetchall()
        return [ModerationWarning(**dict(row)) for row in rows], total

    async def get_warning_stats(self, *, guild_id: int) -> WarningStats:
        """Aggregate warning statistics from active records in one guild."""
        async with self._lock:
            cursor = await self._connection().execute(
                """
                SELECT COUNT(*) AS total_warnings,
                       COUNT(DISTINCT target_id) AS members_warned,
                       COUNT(DISTINCT moderator_id) AS moderators_with_warnings
                FROM moderation_warnings
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            row = await cursor.fetchone()
        return WarningStats(
            total_warnings=int(row["total_warnings"]),
            members_warned=int(row["members_warned"]),
            moderators_with_warnings=int(row["moderators_with_warnings"]),
        )

    async def delete_warning(
        self, *, guild_id: int, target_id: int, warning_id: int
    ) -> ModerationWarning | None:
        """Delete only the requested warning belonging to this guild and member."""
        async with self._lock:
            db = self._connection()
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT warning_id, guild_id, target_id, moderator_id, reason, created_at
                FROM moderation_warnings
                WHERE warning_id = ? AND guild_id = ? AND target_id = ?
                """,
                (warning_id, guild_id, target_id),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return None
            await db.execute(
                """
                DELETE FROM moderation_warnings
                WHERE warning_id = ? AND guild_id = ? AND target_id = ?
                """,
                (warning_id, guild_id, target_id),
            )
            await db.commit()
        return ModerationWarning(**dict(row))

    async def clear_warnings(self, *, guild_id: int, target_id: int) -> int:
        """Delete only one member's warning records from the specified guild."""
        async with self._lock:
            cursor = await self._connection().execute(
                """
                DELETE FROM moderation_warnings
                WHERE guild_id = ? AND target_id = ?
                """,
                (guild_id, target_id),
            )
            await self._connection().commit()
        return cursor.rowcount

    async def update_case_status(self, case_id: int, status: str) -> None:
        if status not in {
            "pending", "completed", "failed", "partial", "expiry_pending", "expired"
        }:
            raise ValueError("Invalid moderation case status.")
        async with self._lock:
            cursor = await self._connection().execute(
                "UPDATE moderation_cases SET status = ? WHERE case_id = ?",
                (status, case_id),
            )
            await self._connection().commit()
            if cursor.rowcount != 1:
                raise LookupError(f"Moderation case {case_id} was not found.")

    async def get_case(self, case_id: int) -> ModerationCase | None:
        async with self._lock:
            cursor = await self._connection().execute(
                "SELECT * FROM moderation_cases WHERE case_id = ?",
                (case_id,),
            )
            row = await cursor.fetchone()
        if row is None:
            return None
        return ModerationCase(**dict(row))

    async def claim_expired_tempbans(self, now: datetime | None = None) -> list[ModerationCase]:
        """Atomically mark due completed tempbans for one expiry-worker pass."""
        cutoff = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        async with self._lock:
            db = self._connection()
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT * FROM moderation_cases
                WHERE action_type = 'tempban'
                  AND status = 'completed'
                  AND expires_at IS NOT NULL
                  AND expires_at <= ?
                ORDER BY expires_at, case_id
                """,
                (cutoff,),
            )
            rows = await cursor.fetchall()
            if rows:
                await db.executemany(
                    """
                    UPDATE moderation_cases
                    SET status = 'expiry_pending'
                    WHERE case_id = ? AND status = 'completed'
                    """,
                    [(row["case_id"],) for row in rows],
                )
            await db.commit()
        return [
            ModerationCase(**{**dict(row), "status": "expiry_pending"})
            for row in rows
        ]

    async def close(self) -> None:
        async with self._lock:
            if self._db is not None:
                await self._db.close()
                self._db = None
