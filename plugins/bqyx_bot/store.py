from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import UserBind


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        await self._run(self._init_schema)

    async def close(self) -> None:
        return None

    async def get_group_army(self, group_id: str) -> int | None:
        row = await self._run(
            self._fetchone,
            "SELECT army_id FROM group_army WHERE group_id = ?",
            (str(group_id),),
        )
        return int(row[0]) if row else None

    async def set_group_army(self, group_id: str, army_id: int) -> None:
        await self._run(
            self._execute,
            """
            INSERT INTO group_army (group_id, army_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                army_id = excluded.army_id,
                updated_at = excluded.updated_at
            """,
            (str(group_id), int(army_id), _utc_now()),
        )

    async def get_user_bind(self, group_id: str, qq_id: str) -> UserBind | None:
        row = await self._run(
            self._fetchone,
            """
            SELECT group_id, qq_id, uid, arch_index
            FROM user_bind
            WHERE group_id = ? AND qq_id = ?
            """,
            (str(group_id), str(qq_id)),
        )
        return self._row_to_bind(row) if row else None

    async def set_user_bind(
        self,
        group_id: str,
        qq_id: str,
        uid: str,
        arch_index: int,
    ) -> None:
        await self._run(
            self._execute,
            """
            INSERT INTO user_bind (group_id, qq_id, uid, arch_index, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(group_id, qq_id) DO UPDATE SET
                uid = excluded.uid,
                arch_index = excluded.arch_index,
                updated_at = excluded.updated_at
            """,
            (str(group_id), str(qq_id), str(uid), int(arch_index), _utc_now()),
        )

    async def list_user_binds(self, group_id: str) -> list[UserBind]:
        rows = await self._run(
            self._fetchall,
            """
            SELECT group_id, qq_id, uid, arch_index
            FROM user_bind
            WHERE group_id = ?
            """,
            (str(group_id),),
        )
        return [self._row_to_bind(row) for row in rows]

    async def merge_user_binds(
        self,
        group_id: str,
        binds: dict[str, tuple[str, int]],
    ) -> tuple[int, int, int]:
        existing = {
            item.qq_id: (item.uid, item.arch_index)
            for item in await self.list_user_binds(group_id)
        }
        new_binds = 0
        updated_binds = 0
        unchanged_binds = 0
        for qq_id, payload in binds.items():
            previous = existing.get(qq_id)
            if previous == payload:
                unchanged_binds += 1
                continue
            await self.set_user_bind(group_id, qq_id, payload[0], payload[1])
            if previous is None:
                new_binds += 1
            else:
                updated_binds += 1
        return new_binds, updated_binds, unchanged_binds

    async def add_exclude(self, group_id: str, qq_id: str) -> bool:
        rowcount = await self._run(
            self._execute,
            """
            INSERT OR IGNORE INTO exclude_at (group_id, qq_id, updated_at)
            VALUES (?, ?, ?)
            """,
            (str(group_id), str(qq_id), _utc_now()),
        )
        return rowcount > 0

    async def remove_exclude(self, group_id: str, qq_id: str) -> bool:
        rowcount = await self._run(
            self._execute,
            "DELETE FROM exclude_at WHERE group_id = ? AND qq_id = ?",
            (str(group_id), str(qq_id)),
        )
        return rowcount > 0

    async def list_exclude(self, group_id: str) -> list[str]:
        rows = await self._run(
            self._fetchall,
            "SELECT qq_id FROM exclude_at WHERE group_id = ? ORDER BY qq_id",
            (str(group_id),),
        )
        return [str(row[0]) for row in rows]

    async def get_session(self) -> tuple[str, dict[str, str]] | None:
        row = await self._run(
            self._fetchone,
            "SELECT uid, cookies_json FROM account_session WHERE id = 1",
        )
        if not row:
            return None
        cookies = json.loads(row[1])
        if not isinstance(cookies, dict):
            return None
        return str(row[0]), {str(k): str(v) for k, v in cookies.items()}

    async def set_session(self, uid: str, cookies: dict[str, str]) -> None:
        await self._run(
            self._execute,
            """
            INSERT INTO account_session (id, uid, cookies_json, updated_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                uid = excluded.uid,
                cookies_json = excluded.cookies_json,
                updated_at = excluded.updated_at
            """,
            (str(uid), json.dumps(cookies, ensure_ascii=False), _utc_now()),
        )

    async def _run(self, func, *args) -> Any:
        async with self._lock:
            return await asyncio.to_thread(func, *args)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS group_army (
                    group_id TEXT PRIMARY KEY,
                    army_id INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_bind (
                    group_id TEXT NOT NULL,
                    qq_id TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    arch_index INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (group_id, qq_id)
                );
                CREATE TABLE IF NOT EXISTS exclude_at (
                    group_id TEXT NOT NULL,
                    qq_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (group_id, qq_id)
                );
                CREATE TABLE IF NOT EXISTS account_session (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    uid TEXT NOT NULL,
                    cookies_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._connect() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.rowcount

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    @staticmethod
    def _row_to_bind(row: tuple[Any, ...]) -> UserBind:
        return UserBind(
            group_id=str(row[0]),
            qq_id=str(row[1]),
            uid=str(row[2]),
            arch_index=int(row[3]),
        )
