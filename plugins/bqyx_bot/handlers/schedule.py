from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types import MessageArray

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
    format_below_text,
    report_date,
    snapshot_from_member,
)

LOG = logging.getLogger("bqyx_bot.schedule")

# 军队排行采集参数：前 1000 名，每页 100
UNION_RANK_LIMIT = 1000
UNION_PAGE_SIZE = 100


async def fetch_union_rank(user) -> list:
    """分页拉取军队排行，直到前 UNION_RANK_LIMIT 个或拉完。"""
    unions = []
    page = 1
    while len(unions) < UNION_RANK_LIMIT:
        page_result = await user.get_union_list(
            page_num=page,
            page_size=UNION_PAGE_SIZE,
        )
        items = list(page_result.unions)
        if not items:
            break
        unions.extend(items)
        total = int(getattr(page_result, "count", 0) or 0)
        if page * UNION_PAGE_SIZE >= total or len(unions) >= UNION_RANK_LIMIT:
            break
        page += 1
    return unions[:UNION_RANK_LIMIT]


class ScheduleHandlers(BqyxServices):
    async def capture_members(self) -> None:
        async with self._lock():
            await self._capture_members()

    async def capture_unions(self) -> None:
        async with self._lock():
            await self._capture_unions()

    @error_reply
    @query_limit
    @registrar.on_group_command("昨日贡献")
    async def check_yesterday_contribution(self, event: GroupMessageEvent) -> None:
        resolved = self._yesterday_limit(event)
        missing = await self._yesterday_below(str(event.group_id), resolved)
        text = format_below_text(resolved, missing)
        if len(text) > 400:
            await self.replies.send_forward_text(event, text)
            return
        await event.reply(text)

    @error_reply
    @query_limit
    @registrar.on_group_command("昨日贡献@")
    async def check_yesterday_contribution_with_at(self, event: GroupMessageEvent) -> None:
        resolved = self._yesterday_limit(event)
        group_id = str(event.group_id)
        missing = await self._yesterday_below(group_id, resolved)
        if not missing:
            await event.reply(format_below_text(resolved, missing))
            return
        await event.reply(rtf=await self._yesterday_at_chain(group_id, missing, resolved))

    def _yesterday_limit(self, event: GroupMessageEvent) -> int:
        limit, _ = parse_format_and_limit(
            event.message.text,
            default_limit=ContributionKind.DAILY.default_limit,
            default_format="文本",
        )
        return limit if limit is not None else ContributionKind.DAILY.default_limit

    async def _yesterday_below(self, group_id: str, limit: int) -> list[YesterdayScore]:
        user, army_id = await self.require_army(group_id)
        _day, scores = await self._yesterday_scores(
            group_id,
            army_id,
            user=user,
            army_cache={},
        )
        return below_limit(scores, limit)

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

    async def _yesterday_scores(
        self,
        group_id: str,
        army_id: int,
        *,
        user,
        army_cache: dict[int, list],
        captured_at: str | None = None,
    ) -> tuple[str, list[YesterdayScore]]:
        previous_day = report_date()
        previous = await self.store.list_member_snapshots(group_id, previous_day)
        if not previous:
            raise BotError(f"没有 {previous_day} 的 成员快照，请等晚上采集完成后再试。")
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

    async def _yesterday_at_chain(
        self,
        group_id: str,
        missing: list[YesterdayScore],
        limit: int,
    ) -> MessageArray:
        binds = await self.store.list_user_binds(group_id)
        uid_to_qq = {item.uid: item.qq_id for item in binds}
        exclude_list = set(await self.store.list_exclude(group_id))
        group_qq_ids: set[str] = set()
        try:
            group_members = await self.api.qq.query.get_group_member_list(int(group_id))
            group_qq_ids = {str(member.user_id) for member in group_members}
        except Exception:
            LOG.exception("获取群 %s 成员列表失败，昨日贡献将不 @", group_id)

        chain = MessageArray()
        chain.add_text(f"以下成员昨日贡献低于 {limit}：\n")
        for member in missing:
            qq_id = uid_to_qq.get(member.uid)
            chain.add_text(f"- {member.nickname} (贡献: {member.yesterday}) ")
            if qq_id and qq_id in group_qq_ids:
                if qq_id in exclude_list:
                    chain.add_text(f"(免@: {qq_id})")
                else:
                    chain.add_at(qq_id)
            elif qq_id:
                chain.add_text("(已离群)")
            else:
                chain.add_text("(未绑定)")
            chain.add_text("\n")
        return chain
