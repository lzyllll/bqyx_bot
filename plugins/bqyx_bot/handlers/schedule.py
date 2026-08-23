from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from ..context import BqyxServices
from ..models import MemberSnapshot, UnionSnapshot
from ..schedule import capture_date, report_date, snapshot_from_member

LOG = logging.getLogger("bqyx_bot.schedule")

# 军队排行采集参数：前 1000 名，每页 100
UNION_RANK_LIMIT = 1000
UNION_PAGE_SIZE = 100


async def fetch_union_rank(user, limit: int = UNION_RANK_LIMIT) -> list:
    """分页拉取军队排行（每页 100，即每次扩 100），直到 limit 或上限 1000 或拉完。"""
    limit = min(int(limit), UNION_RANK_LIMIT)
    unions = []
    page = 1
    while len(unions) < limit:
        page_result = await user.get_union_list(
            page_num=page,
            page_size=UNION_PAGE_SIZE,
        )
        items = list(page_result.unions)
        if not items:
            break
        unions.extend(items)
        total = int(getattr(page_result, "count", 0) or 0)
        if len(unions) >= total or len(unions) >= limit:
            break
        page += 1
    return unions[:limit]


class ScheduleHandlers(BqyxServices):
    async def capture_members(self) -> None:
        async with self._lock():
            await self._capture_members()

    async def capture_unions(self) -> None:
        # 23:59 触发后先等 50 秒（约 23:59:50），更接近零点，确保当日贡献数据完整
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
        async with self._lock():
            await self._capture_unions()

    def _lock(self) -> asyncio.Lock:
        lock = getattr(self, "_nightly_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._nightly_lock = lock
        return lock

    async def _capture_members(self) -> None:
        groups = await self.store.list_group_armies()
        if not groups:
            LOG.info("没有已绑定军队的群，跳过成员采集")
            return

        user = await self.account.get_user()
        snapshot_day = capture_date()
        captured_at = datetime.now(timezone.utc).isoformat()
        army_cache: dict[int, list] = {}
        ok = 0
        for group_id, army_id in groups:
            try:
                items = await self._live_snapshots(
                    user,
                    army_cache,
                    group_id,
                    army_id,
                    snapshot_day,
                    captured_at,
                )
                await self.store.replace_member_snapshots(
                    group_id,
                    army_id,
                    snapshot_day,
                    items,
                )
                ok += 1
                LOG.info(
                    "已采集群 %s 军队 %s 成员 %s 人（%s）",
                    group_id,
                    army_id,
                    len(items),
                    snapshot_day,
                )
            except Exception:
                LOG.exception("采集群 %s 军队 %s 失败", group_id, army_id)
        LOG.info("成员采集完成：%s/%s 个群", ok, len(groups))

    async def _capture_unions(self) -> None:
        """23:59 采集前 1000 军队排行。

        接口只有总贡献 contribution，没有今日贡献，因此只能在接近零点采集，
        用相邻两天总贡献的差值作为当日日贡（today_contribution）。
        """
        user = await self.account.get_user()
        snapshot_day = capture_date()
        captured_at = datetime.now(timezone.utc).isoformat()

        unions = await fetch_union_rank(user)
        if not unions:
            LOG.warning("军队排行采集为空，跳过（%s）", snapshot_day)
            return

        ranked = sorted(
            unions,
            key=lambda u: int(getattr(u, "contribution", 0) or 0),
            reverse=True,
        )[:UNION_RANK_LIMIT]

        yesterday = report_date()
        prev_map = {
            item.union_id: item.contribution
            for item in await self.store.list_union_snapshots(yesterday)
        }

        rows = []
        for index, union in enumerate(ranked, 1):
            contribution = int(getattr(union, "contribution", 0) or 0)
            prev = prev_map.get(int(getattr(union, "id", 0) or 0))
            today_contribution = max(contribution - prev, 0) if prev is not None else 0
            rows.append(
                UnionSnapshot(
                    snapshot_date=snapshot_day,
                    rank=index,
                    union_id=int(getattr(union, "id", 0) or 0),
                    name=str(getattr(union, "name", "") or ""),
                    level=int(getattr(union, "level", 0) or 0),
                    members_num=int(getattr(union, "members_num", 0) or 0),
                    contribution=contribution,
                    today_contribution=today_contribution,
                    captured_at=captured_at,
                )
            )
        await self.store.replace_union_snapshots(snapshot_day, rows)
        LOG.info("军队排行采集完成：%s 个军队（%s）", len(rows), snapshot_day)

    async def _live_snapshots(
        self,
        user,
        army_cache: dict[int, list],
        group_id: str,
        army_id: int,
        snapshot_day: str,
        captured_at: str,
    ) -> list[MemberSnapshot]:
        if army_id not in army_cache:
            army_cache[army_id] = list(await user.get_members(army_id))
        return [
            snapshot_from_member(
                group_id,
                army_id,
                snapshot_day,
                member,
                captured_at,
            )
            for member in army_cache[army_id]
        ]
