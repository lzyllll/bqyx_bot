from __future__ import annotations

import asyncio
import base64
import logging
import time
from datetime import datetime, timezone

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..context import BqyxServices
from ..errors import BotError
from ..hooks import error_reply, query_limit
from ..models import ContributionKind, MemberSnapshot, UnionSnapshot
from ..parsing import parse_format_and_limit
from ..schedule import (
    YesterdayScore,
    below_limit,
    calculate_yesterday,
    capture_date,
    report_date,
    snapshot_from_member,
)

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


def apply_yesterday_to_members(
    members: list,
    scores: list[YesterdayScore],
    default: int = 0,
) -> list:
    """把成员对象的「日贡」字段（detail.conDay）覆盖为昨日贡献值，供 bqyx_api 图片/文本渲染。

    昨日贡献只存在于 scores 里，不修改渲染数据源的话，图片/文本显示的是实时 conDay（今天）。
    新成员（昨天不在军队、无分数）按 default（0）处理。
    """
    score_map = {score.uid: score.yesterday for score in scores}
    for member in members:
        detail = getattr(member, "detail", None)
        if detail is None:
            continue
        uid = str(getattr(member, "uid", "") or "")
        detail.conDay = score_map.get(uid, default)
    return members


def sort_members_by_yesterday(members: list, scores: list[YesterdayScore]) -> list:
    """按昨日贡献降序排列成员（渲染顺序）；无分数成员视为 0 排后面。"""
    score_map = {score.uid: score.yesterday for score in scores}
    members.sort(key=lambda m: -score_map.get(str(getattr(m, "uid", "") or ""), 0))
    return members


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

    @error_reply
    @query_limit
    @registrar.on_group_command("昨日贡献")
    async def check_yesterday_contribution(self, event: GroupMessageEvent) -> None:
        """昨日贡献：默认全部成员图片；加值 '昨日贡献 1400' 只显示低于该值的成员（bqyx_api 成员图片渲染）。"""
        limit, _ = parse_format_and_limit(
            event.message.text,
            default_limit=None,
            default_format="图片",
        )
        group_id = str(event.group_id)
        user, army_id = await self.require_army(group_id)
        army_cache: dict[int, list] = {}
        day, scores = await self._yesterday_scores(
            group_id,
            army_id,
            user=user,
            army_cache=army_cache,
        )
        members = army_cache.get(army_id) or list(await user.get_members(army_id))
        # 渲染前把成员的「日贡」列覆盖为昨日贡献值，图片/文本显示昨日贡献而非实时今日贡献
        apply_yesterday_to_members(members, scores)
        # 按昨日贡献降序渲染（游戏接口返回顺序与贡献无关）
        sort_members_by_yesterday(members, scores)
        if limit is not None:
            below = {score.uid for score in below_limit(scores, limit)}
            members = [member for member in members if str(member.uid) in below]
        await self.replies.send_members(event, members, "图片")

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
            # 无前一天基线（首次采集）时无法计算日贡，存 None 以便查询时不展示
            today_contribution = max(contribution - prev, 0) if prev is not None else None
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
        group_id: str,
        army_id: int,
        *,
        user,
        army_cache: dict[int, list],
        captured_at: str | None = None,
    ) -> tuple[str, list[YesterdayScore]]:
        """昨日贡献：读昨天快照，实时拉取当前数据对比计算。"""
        previous_day = report_date()
        previous = await self.store.list_member_snapshots(group_id, previous_day)
        if not previous:
            raise BotError(f"没有 {previous_day} 的成员快照，请等晚上采集完成后再试。")
        current = await self._live_snapshots(
            user,
            army_cache,
            group_id,
            army_id,
            previous_day,
            captured_at or datetime.now(timezone.utc).isoformat(),
        )
        return previous_day, calculate_yesterday(previous, current)

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
