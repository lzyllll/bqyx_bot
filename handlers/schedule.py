from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from astrbot.api.event import AstrMessageEvent, filter

from ..context import BqyxServices
from ..errors import ArmyNotBoundError, BotError, GroupOnlyError
from ..hooks import command_rate_limit, error_reply
from ..models import MemberSnapshot, UnionSnapshot
from ..parsing import parse_format_and_limit
from ..schedule import (
    YesterdayScore,
    below_limit,
    calculate_yesterday,
    capture_date,
    compute_daily_from_snapshots,
    report_date,
    snapshot_from_member,
)

LOG = logging.getLogger("astrbot_plugin_bqyx.schedule")

UNION_RANK_LIMIT = 1000
UNION_PAGE_SIZE = 100


async def fetch_union_rank(user, limit: int = UNION_RANK_LIMIT) -> list:
    """分页拉取军队排行（每页 100），直到 limit 或上限 1000 或拉完。"""
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


def apply_yesterday_to_members(
    members: list,
    scores: list[YesterdayScore],
    default: int = 0,
) -> list:
    score_map = {score.uid: score.yesterday for score in scores}
    for member in members:
        detail = getattr(member, "detail", None)
        if detail is None:
            continue
        uid = str(getattr(member, "uid", "") or "")
        detail.conDay = score_map.get(uid, default)
    return members


def sort_members_by_yesterday(members: list, scores: list[YesterdayScore]) -> list:
    score_map = {score.uid: score.yesterday for score in scores}
    members.sort(key=lambda m: -score_map.get(str(getattr(m, "uid", "") or ""), 0))
    return members


class ScheduleHandlers(BqyxServices):
    async def prune_command_call_stats(self) -> None:
        """每日清理超过两个月保留期的指令调用统计。"""
        removed = await self.store.prune_command_call_stats()
        LOG.info("已清理 %s 条过期指令调用统计", removed)

    async def capture_members_and_cal_real(self) -> None:
        async with self._lock():
            await self._capture_members_and_cal_real()

    async def capture_members(self) -> None:
        await self.capture_members_and_cal_real()

    async def _capture_members(self) -> None:
        await self._capture_members_and_cal_real()


    async def capture_unions(self) -> None:
        deadline = time.monotonic() + 50
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
        async with self._lock():
            await self._capture_unions()

    @error_reply
    @command_rate_limit(name="昨日贡献")
    @filter.command("昨日贡献")
    async def check_yesterday_contribution(self, event: AstrMessageEvent) -> None:
        """昨日贡献：默认全部成员图片；加值 '昨日贡献 1400' 只显示低于该值的成员。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        limit, _ = parse_format_and_limit(
            event.message_str,
            default_limit=None,
            default_format="图片",
        )
        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            raise ArmyNotBoundError()
        user = await self.account.get_user()
        army_cache: dict[int, list] = {}
        day, scores = await self._yesterday_scores(
            army_id,
            user=user,
            army_cache=army_cache,
        )
        members = army_cache.get(army_id) or list(await user.get_members(army_id))
        apply_yesterday_to_members(members, scores)
        sort_members_by_yesterday(members, scores)
        if limit is not None:
            below = {score.uid for score in below_limit(scores, limit)}
            members = [member for member in members if str(member.uid) in below]
        bind = await self.optional_bind(group_id, str(event.get_sender_id()))
        for res in await self.replies.build_members(
            event,
            members,
            "图片",
            title="昨日贡献",
            uid=bind.uid if bind else None,
        ):
            yield res

    def _lock(self) -> asyncio.Lock:
        lock = getattr(self, "_nightly_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._nightly_lock = lock
        return lock

    async def _capture_members_and_cal_real(self) -> None:
        groups = await self.store.list_group_armies()
        if not groups:
            LOG.info("没有已绑定军队的群，跳过成员采集")
            return

        user = await self.account.get_user()
        snapshot_day = capture_date()
        captured_at = datetime.now(timezone.utc).isoformat()
        army_ids = sorted({int(army_id) for _, army_id in groups})
        army_cache: dict[int, list] = {}
        ok = 0
        for army_id in army_ids:
            for attempt in range(3):
                try:
                    items = await self._live_snapshots(
                        user,
                        army_cache,
                        army_id,
                        snapshot_day,
                        captured_at,
                    )
                    await self.store.replace_member_snapshots(
                        army_id,
                        snapshot_day,
                        items,
                    )
                    ok += 1
                    LOG.info(
                        "已采集军队 %s 成员 %s 人（%s）",
                        army_id,
                        len(items),
                        snapshot_day,
                    )
                    break
                except Exception:
                    if attempt < 2:
                        LOG.warning(
                            "采集军队 %s 失败，15 秒后重试（%s/3）",
                            army_id,
                            attempt + 1,
                        )
                        await asyncio.sleep(15)
                    else:
                        LOG.exception("采集军队 %s 失败（已重试 3 次）", army_id)
        LOG.info("成员采集完成：%s/%s 个军队", ok, len(army_ids))
        await self._compute_yesterday_daily(army_ids, snapshot_day, captured_at)

    async def _compute_yesterday_daily(
        self,
        army_ids: list[int],
        today: str,
        computed_at: str,
    ) -> None:
        yesterday = report_date()
        for army_id in army_ids:
            try:
                prev = await self.store.list_member_snapshots(army_id, yesterday)
                curr = await self.store.list_member_snapshots(army_id, today)
                if not prev or not curr:
                    continue
                dailies = compute_daily_from_snapshots(
                    prev, curr, yesterday, computed_at
                )
                await self.store.upsert_member_daily(dailies)
                LOG.info(
                    "已计算军队 %s 昨日 daily %s 人（%s）",
                    army_id,
                    len(dailies),
                    yesterday,
                )
            except Exception:
                LOG.exception("计算军队 %s 昨日 daily 失败", army_id)

    async def _capture_unions(self) -> None:
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
            today_contribution = (
                max(contribution - prev, 0) if prev is not None else None
            )
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

    async def _yesterday_scores(
        self,
        army_id: int,
        *,
        user,
        army_cache: dict[int, list],
        captured_at: str | None = None,
    ) -> tuple[str, list[YesterdayScore]]:
        previous_day = report_date()
        previous = await self.store.list_member_snapshots(army_id, previous_day)
        if not previous:
            raise BotError(f"没有 {previous_day} 的成员快照，请等晚上采集完成后再试。")
        current = await self._live_snapshots(
            user,
            army_cache,
            army_id,
            previous_day,
            captured_at or datetime.now(timezone.utc).isoformat(),
        )
        return previous_day, calculate_yesterday(previous, current)

    async def _live_snapshots(
        self,
        user,
        army_cache: dict[int, list],
        army_id: int,
        snapshot_day: str,
        captured_at: str,
    ) -> list[MemberSnapshot]:
        if army_id not in army_cache:
            army_cache[army_id] = list(await user.get_members(army_id))
        return [
            snapshot_from_member(
                army_id,
                snapshot_day,
                member,
                captured_at,
            )
            for member in army_cache[army_id]
        ]
