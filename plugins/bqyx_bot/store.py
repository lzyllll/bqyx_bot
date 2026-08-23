from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .models import MemberSnapshot, UnionSnapshot, UserBind

SHANGHAI = timezone(timedelta(hours=8))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteStore:
    def __init__(self, path: Path, retention_days: int = 3) -> None:
        self.path = Path(path)
        self.retention_days = retention_days
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

    async def list_group_armies(self) -> list[tuple[str, int]]:
        rows = await self._run(
            self._fetchall,
            "SELECT group_id, army_id FROM group_army ORDER BY group_id",
        )
        return [(str(row[0]), int(row[1])) for row in rows]

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

    async def replace_member_snapshots(
        self,
        group_id: str,
        army_id: int,
        snapshot_date: str,
        items: list[MemberSnapshot],
    ) -> None:
        """覆盖式写入某群军队在某一天（snapshot_date）的成员快照。

        先删除该 group_id + snapshot_date 的旧记录，再整体插入当天新快照，
        保证每个「群 × 日期」只有一份最新采集结果。
        """
        await self._run(
            self._replace_member_snapshots,
            str(group_id),
            int(army_id),
            str(snapshot_date),
            items,
        )

    async def list_member_snapshots(
        self,
        group_id: str,
        snapshot_date: str,
    ) -> list[MemberSnapshot]:
        rows = await self._run(
            self._fetchall,
            """
            SELECT group_id, army_id, snapshot_date, uid, arch_index,
                   nickname, contribution, con_day, this_week, captured_at
            FROM member_snapshot
            WHERE group_id = ? AND snapshot_date = ?
            ORDER BY contribution DESC, nickname
            """,
            (str(group_id), str(snapshot_date)),
        )
        return [self._row_to_snapshot(row) for row in rows]

    async def replace_union_snapshots(
        self,
        snapshot_date: str,
        items: list[UnionSnapshot],
    ) -> None:
        """覆盖式写入某一天的军队排行快照（前 1000 名）。

        先删除该 snapshot_date 的旧记录，再整体插入当天新快照，
        并顺手清理超过保留天数的历史军队快照。
        """
        await self._run(
            self._replace_union_snapshots,
            str(snapshot_date),
            items,
        )

    async def list_union_snapshots(self, snapshot_date: str) -> list[UnionSnapshot]:
        rows = await self._run(
            self._fetchall,
            """
            SELECT snapshot_date, rank, union_id, name, level,
                   members_num, contribution, today_contribution, captured_at
            FROM union_snapshot
            WHERE snapshot_date = ?
            ORDER BY rank
            """,
            (str(snapshot_date),),
        )
        return [self._row_to_union_snapshot(row) for row in rows]

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
                -- 成员每日贡献快照：每天 23:30 全量覆盖写入一份，
                -- 存当天每个成员的总贡献/今日贡献/本周贡献等指标。
                -- 「昨日贡献」不在此表中，由前后两天快照对比计算得出。
                CREATE TABLE IF NOT EXISTS member_snapshot (
                    group_id TEXT NOT NULL,
                    army_id INTEGER NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    arch_index INTEGER NOT NULL,
                    nickname TEXT NOT NULL,
                    contribution INTEGER NOT NULL DEFAULT 0,
                    con_day INTEGER NOT NULL,
                    this_week INTEGER NOT NULL,
                    captured_at TEXT NOT NULL,
                    PRIMARY KEY (group_id, snapshot_date, uid, arch_index)
                );
                -- 军队排行快照：每天 23:59 全量覆盖写入一份（前 1000 名）。
                -- 接口只有总贡献，today_contribution 由相邻两天快照对比得出。
                CREATE TABLE IF NOT EXISTS union_snapshot (
                    snapshot_date TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    union_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 0,
                    members_num INTEGER NOT NULL DEFAULT 0,
                    contribution INTEGER NOT NULL DEFAULT 0,
                    today_contribution INTEGER NOT NULL DEFAULT 0,
                    captured_at TEXT NOT NULL,
                    PRIMARY KEY (snapshot_date, union_id)
                );
                """
            )
            self._ensure_snapshot_contribution(conn)

    def _ensure_snapshot_contribution(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(member_snapshot)").fetchall()}
        if "contribution" not in columns:
            conn.execute(
                "ALTER TABLE member_snapshot ADD COLUMN contribution INTEGER NOT NULL DEFAULT 0"
            )

    def _replace_member_snapshots(
        self,
        group_id: str,
        army_id: int,
        snapshot_date: str,
        items: list[MemberSnapshot],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM member_snapshot WHERE group_id = ? AND snapshot_date = ?",
                (group_id, snapshot_date),
            )
            conn.executemany(
                """
                INSERT INTO member_snapshot (
                    group_id, army_id, snapshot_date, uid, arch_index,
                    nickname, contribution, con_day, this_week, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        group_id,
                        army_id,
                        snapshot_date,
                        item.uid,
                        int(item.arch_index),
                        item.nickname,
                        int(item.contribution),
                        int(item.con_day),
                        int(item.this_week),
                        item.captured_at,
                    )
                    for item in items
                ],
            )
            self._prune_old_snapshots(conn)
            conn.commit()

    def _prune_old_snapshots(self, conn: sqlite3.Connection) -> None:
        """删除超过保留天数的历史快照。

        snapshot_date 是 yyyy-mm-dd 字符串，可直接按字典序比较。
        保留最近 retention_days 份（含当天）；retention_days <= 0 表示不清理。
        """
        if self.retention_days <= 0:
            return
        cutoff = (
            datetime.now(SHANGHAI) - timedelta(days=self.retention_days - 1)
        ).date().isoformat()
        conn.execute(
            "DELETE FROM member_snapshot WHERE snapshot_date < ?",
            (cutoff,),
        )

    def _replace_union_snapshots(
        self,
        snapshot_date: str,
        items: list[UnionSnapshot],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM union_snapshot WHERE snapshot_date = ?",
                (snapshot_date,),
            )
            conn.executemany(
                """
                INSERT INTO union_snapshot (
                    snapshot_date, rank, union_id, name, level,
                    members_num, contribution, today_contribution, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_date,
                        int(item.rank),
                        int(item.union_id),
                        item.name,
                        int(item.level),
                        int(item.members_num),
                        int(item.contribution),
                        int(item.today_contribution),
                        item.captured_at,
                    )
                    for item in items
                ],
            )
            self._prune_old_union_snapshots(conn)
            conn.commit()

    def _prune_old_union_snapshots(self, conn: sqlite3.Connection) -> None:
        """删除超过保留天数的军队排行快照（保留 3 天）。

        retention_days <= 0 表示不清理。
        """
        if self.retention_days <= 0:
            return
        cutoff = (
            datetime.now(SHANGHAI) - timedelta(days=self.retention_days - 1)
        ).date().isoformat()
        conn.execute(
            "DELETE FROM union_snapshot WHERE snapshot_date < ?",
            (cutoff,),
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

    @staticmethod
    def _row_to_snapshot(row: tuple[Any, ...]) -> MemberSnapshot:
        return MemberSnapshot(
            group_id=str(row[0]),
            army_id=int(row[1]),
            snapshot_date=str(row[2]),
            uid=str(row[3]),
            arch_index=int(row[4]),
            nickname=str(row[5]),
            contribution=int(row[6]),
            con_day=int(row[7]),
            this_week=int(row[8]),
            captured_at=str(row[9]),
        )

    @staticmethod
    def _row_to_union_snapshot(row: tuple[Any, ...]) -> UnionSnapshot:
        return UnionSnapshot(
            snapshot_date=str(row[0]),
            rank=int(row[1]),
            union_id=int(row[2]),
            name=str(row[3]),
            level=int(row[4]),
            members_num=int(row[5]),
            contribution=int(row[6]),
            today_contribution=int(row[7]),
            captured_at=str(row[8]),
        )
