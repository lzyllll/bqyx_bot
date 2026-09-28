"""军队排行查询：昨日/今日日贡、本周/上周周贡、实时军队排行（图片渲染，高亮本军）。"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from astrbot.api.event import AstrMessageEvent, filter

from ..context import BqyxServices
from ..errors import BotError
from ..hooks import (
    error_reply,
    last_week_union_limit,
    this_week_union_limit,
    total_union_limit,
    union_live_limit,
    yesterday_union_limit,
)
from ..models import UnionSnapshot
from ..render.union_rank_render import UnionRankRenderer
from ..schedule import (
    SHANGHAI,
    as_shanghai,
    last_sunday,
    last_week_label,
    last_week_range,
    report_date,
    this_week_label,
)
from .schedule import UNION_RANK_LIMIT, fetch_union_rank

# 默认以本军排行为中心，前后各取 6 名；可指定范围，但窗口上限 20
RANK_WINDOW = 6
MAX_WINDOW = 20


def _spec_need(spec: tuple[int, int] | int | None, fallback: int) -> int:
    """指定范围需要覆盖到的名次；无参数时返回 fallback。"""
    if spec is None:
        return fallback
    if isinstance(spec, int):
        return spec
    return spec[1]


def _member_change(
    current_members: int, prev: UnionSnapshot | None
) -> str | None:
    """军队人数相对基线快照的变动标注；无变动或缺少基线返回 None。"""
    if prev is None:
        return None
    diff = int(current_members) - int(prev.members_num)
    if diff == 0:
        return None
    return f"+{diff}" if diff > 0 else str(diff)


def _contribution_change(
    current_contribution: int, prev: UnionSnapshot | None
) -> str | None:
    """总贡献相对基线快照的变动标注；无变动或缺少基线返回 None。"""
    if prev is None:
        return None
    diff = int(current_contribution) - int(prev.contribution)
    if diff == 0:
        return None
    return f"+{diff}" if diff > 0 else str(diff)


def apply_weekly_contribution(
    items: list[UnionSnapshot],
    baseline: dict[int, UnionSnapshot],
) -> list[UnionSnapshot]:
    """用相对基线快照的总贡献差覆盖 today_contribution，作为周贡。"""
    result = []
    for item in items:
        prev = baseline.get(int(item.union_id))
        weekly = (
            max(int(item.contribution) - int(prev.contribution), 0)
            if prev is not None
            else None
        )
        result.append(replace(item, today_contribution=weekly))
    return result


def snapshots_from_unions(
    unions: list, day: str, captured_at: str
) -> list[UnionSnapshot]:
    """把实时军队列表转成 UnionSnapshot（today_contribution 先留空）。"""
    items = []
    for union in unions:
        items.append(
            UnionSnapshot(
                snapshot_date=day,
                rank=0,
                union_id=int(getattr(union, "id", 0) or 0),
                name=str(getattr(union, "name", "") or ""),
                level=int(getattr(union, "level", 0) or 0),
                members_num=int(getattr(union, "members_num", 0) or 0),
                contribution=int(getattr(union, "contribution", 0) or 0),
                today_contribution=None,
                captured_at=captured_at,
            )
        )
    return items


def parse_rank_range(text: str) -> tuple[int, int] | int | None:
    """解析排行参数：'A-B' 区间 / 'N' 中心排行 / None（以本军为中心）。"""
    tokens = (text or "").split()[1:]
    for token in tokens:
        match = re.match(r"^(\d{1,4})-(\d{1,4})$", token)
        if match:
            return int(match.group(1)), int(match.group(2))
        if token.isdigit():
            return int(token)
    return None


def resolve_rank_spec(
    spec: tuple[int, int] | int | None,
    count: int,
) -> tuple[int | None, int]:
    """把排行参数解析为（中心排行, 窗口）。count 为榜单总行数。"""
    if spec is None:
        return None, RANK_WINDOW
    if isinstance(spec, int):
        return max(1, min(spec, count)), RANK_WINDOW
    low, high = spec
    low, high = max(1, min(low, high)), max(1, max(low, high))
    low, high = min(low, count), min(high, count)
    center = (low + high) // 2
    window = min(max(center - low, high - center), MAX_WINDOW)
    return center, window


def _rank_rows(
    items: list[UnionSnapshot],
    value_key: str,
    army_id: int,
    *,
    window: int = RANK_WINDOW,
    center_rank: int | None = None,
) -> tuple[list[dict], int | None]:
    ranked = sorted(
        items,
        key=lambda item: int(getattr(item, value_key, 0) or 0),
        reverse=True,
    )
    window = max(0, min(window, MAX_WINDOW))
    if center_rank is None:
        center_rank = next(
            (
                i + 1
                for i, item in enumerate(ranked)
                if int(item.union_id) == int(army_id)
            ),
            None,
        )
        if center_rank is None:
            return [], None
    center_rank = max(1, min(center_rank, len(ranked)))
    start = max(0, center_rank - 1 - window)
    end = min(len(ranked), center_rank + window)
    rows = []
    highlight = None
    for pos in range(start, end):
        item = ranked[pos]
        if int(item.union_id) == int(army_id):
            highlight = pos + 1
        rows.append(
            {
                "rank": pos + 1,
                "union_id": item.union_id,
                "name": item.name,
                "members_num": item.members_num,
                "contribution": item.contribution,
                "today_contribution": item.today_contribution,
                "highlight": int(item.union_id) == int(army_id),
            }
        )
    return rows, highlight


def _fmt_local(iso_utc: str) -> str:
    try:
        return (
            datetime.fromisoformat(iso_utc)
            .astimezone(SHANGHAI)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except Exception:
        return iso_utc


class UnionRankHandlers(BqyxServices):
    @error_reply
    @yesterday_union_limit
    @filter.command("昨日日贡排行", alias={"昨日贡献排行"})
    async def yesterday_union_rank(self, event: AstrMessageEvent) -> None:
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        day = report_date()
        snapshots = await self.store.list_union_snapshots(day)
        if not snapshots:
            yield self.replies.markdown_warn(
                event,
                f"还没有 {day} 的军队排行快照，请等今晚 23:59 采集后再试。",
            )
            return
        if all(item.today_contribution is None for item in snapshots):
            yield self.replies.markdown_warn(
                event,
                f"没有 {day} 的前一天军队排行快照，昨日日贡暂无法计算，请等今晚采集后再试。",
            )
            return
        spec = parse_rank_range(event.message_str)
        center_rank, window = resolve_rank_spec(spec, len(snapshots))
        rows, highlight = _rank_rows(
            snapshots,
            "today_contribution",
            army_id,
            window=window,
            center_rank=center_rank,
        )
        if not rows:
            yield self.replies.markdown_warn(event, "指定的排行范围无效。")
            return
        if spec is None and highlight is None:
            yield self.replies.markdown_warn(event, "本群军队不在前 1000 排行中。")
            return
        await self._with_member_change(rows)
        yield await self._send_rank(
            event,
            title="昨日日贡排行",
            date_label=day,
            rows=rows,
            captured_at=snapshots[0].captured_at,
        )

    @error_reply
    @union_live_limit
    @filter.command("今日日贡排行", alias={"今日贡献排行"})
    async def today_union_rank(self, event: AstrMessageEvent) -> None:
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user = await self.account.get_user()
        day = report_date()
        prev_map = {
            item.union_id: item
            for item in await self.store.list_union_snapshots(day)
        }
        if not prev_map:
            yield self.replies.markdown_warn(
                event,
                f"还没有 {day} 的军队排行快照，请等今晚 23:59 采集后再试。",
            )
            return

        unions = await fetch_union_rank(user)
        if not unions:
            yield self.replies.markdown_warn(event, "获取军队排行失败，请稍后再试。")
            return
        captured_at = datetime.now(timezone.utc).isoformat()
        items = []
        for union in unions:
            union_id = int(getattr(union, "id", 0) or 0)
            contribution = int(getattr(union, "contribution", 0) or 0)
            prev = prev_map.get(union_id)
            items.append(
                UnionSnapshot(
                    snapshot_date=day,
                    rank=0,
                    union_id=union_id,
                    name=str(getattr(union, "name", "") or ""),
                    level=int(getattr(union, "level", 0) or 0),
                    members_num=int(getattr(union, "members_num", 0) or 0),
                    contribution=contribution,
                    today_contribution=(
                        max(contribution - prev.contribution, 0)
                        if prev is not None
                        else None
                    ),
                    captured_at=captured_at,
                )
            )
        spec = parse_rank_range(event.message_str)
        center_rank, window = resolve_rank_spec(spec, len(items))
        rows, highlight = _rank_rows(
            items,
            "today_contribution",
            army_id,
            window=window,
            center_rank=center_rank,
        )
        if not rows:
            yield self.replies.markdown_warn(event, "指定的排行范围无效。")
            return
        if spec is None and highlight is None:
            yield self.replies.markdown_warn(event, "本群军队不在前 1000 排行中。")
            return
        for row in rows:
            prev = prev_map.get(int(row["union_id"]))
            row["member_change"] = _member_change(row["members_num"], prev)
        yield await self._send_rank(
            event,
            title="今日日贡排行（实时）",
            date_label=day,
            rows=rows,
            captured_at=captured_at,
        )

    @error_reply
    @total_union_limit
    @filter.command("实时军队排行", alias={"军队排行"})
    async def union_rank(self, event: AstrMessageEvent) -> None:
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user = await self.account.get_user()
        day = report_date()
        spec = parse_rank_range(event.message_str)
        cache = await self.store.list_union_snapshots(day)
        snapshots = await self._live_union_snapshots(
            user, day, spec, army_id, cache
        )
        if not snapshots:
            yield self.replies.markdown_warn(event, "获取军队排行失败，请稍后再试。")
            return
        center_rank, window = resolve_rank_spec(spec, len(snapshots))
        rows, highlight = _rank_rows(
            snapshots,
            "contribution",
            army_id,
            window=window,
            center_rank=center_rank,
        )
        if not rows:
            yield self.replies.markdown_warn(event, "指定的排行范围无效。")
            return
        if spec is None and highlight is None:
            yield self.replies.markdown_warn(event, "本群军队不在前 1000 排行中。")
            return
        await self._with_member_change(rows)
        prev_map = {item.union_id: item for item in cache}
        for row in rows:
            row["contribution_delta"] = _contribution_change(
                row["contribution"],
                prev_map.get(int(row["union_id"])),
            )
        yield await self._send_rank(
            event,
            title="军队总贡献排行",
            date_label=day,
            rows=rows,
            captured_at=snapshots[0].captured_at,
            show_daily=False,
        )

    @error_reply
    @this_week_union_limit
    @filter.command("本周周贡排行", alias={"本周周贡"})
    async def this_week_union_rank(self, event: AstrMessageEvent) -> None:
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user = await self.account.get_user()
        baseline_day = last_sunday().isoformat()
        prev_items = await self.store.list_union_snapshots(baseline_day)
        if not prev_items:
            yield self.replies.markdown_warn(
                event,
                f"还没有 {baseline_day} 的军队排行快照，无法计算本周周贡，请等采集满一周后再试。",
            )
            return
        unions = await fetch_union_rank(user)
        if not unions:
            yield self.replies.markdown_warn(event, "获取军队排行失败，请稍后再试。")
            return
        captured_at = datetime.now(timezone.utc).isoformat()
        live_items = snapshots_from_unions(
            unions,
            as_shanghai().date().isoformat(),
            captured_at,
        )
        items = apply_weekly_contribution(
            live_items,
            {item.union_id: item for item in prev_items},
        )
        yield await self._send_weekly_rank(
            event,
            items=items,
            army_id=army_id,
            spec=parse_rank_range(event.message_str),
            title="本周周贡排行（实时）",
            date_label=this_week_label(),
            captured_at=captured_at,
            member_prev_day=baseline_day,
            missing_baseline_message=(
                f"没有 {baseline_day} 的匹配军队，本周周贡暂无法计算。"
            ),
        )

    @error_reply
    @last_week_union_limit
    @filter.command("上周周贡排行", alias={"上周周贡"})
    async def last_week_union_rank(self, event: AstrMessageEvent) -> None:
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        start_day, end_day = last_week_range()
        end_items = await self.store.list_union_snapshots(end_day)
        if not end_items:
            yield self.replies.markdown_warn(
                event,
                f"还没有 {end_day} 的军队排行快照，无法计算上周周贡，请等采集满一周后再试。",
            )
            return
        start_items = await self.store.list_union_snapshots(start_day)
        if not start_items:
            yield self.replies.markdown_warn(
                event,
                f"还没有 {start_day} 的军队排行快照，无法计算上周周贡，请等采集满两周后再试。",
            )
            return
        items = apply_weekly_contribution(
            end_items,
            {item.union_id: item for item in start_items},
        )
        yield await self._send_weekly_rank(
            event,
            items=items,
            army_id=army_id,
            spec=parse_rank_range(event.message_str),
            title="上周周贡排行",
            date_label=last_week_label(),
            captured_at=end_items[0].captured_at,
            member_prev_day=start_day,
            missing_baseline_message=(
                f"没有 {start_day} 的匹配军队，上周周贡暂无法计算。"
            ),
        )

    async def _send_weekly_rank(
        self,
        event: AstrMessageEvent,
        *,
        items: list[UnionSnapshot],
        army_id: int,
        spec: tuple[int, int] | int | None,
        title: str,
        date_label: str,
        captured_at: str,
        member_prev_day: str,
        missing_baseline_message: str,
    ) -> MessageEventResult:
        if all(item.today_contribution is None for item in items):
            return self.replies.markdown_warn(event, missing_baseline_message)
        center_rank, window = resolve_rank_spec(spec, len(items))
        rows, highlight = _rank_rows(
            items,
            "today_contribution",
            army_id,
            window=window,
            center_rank=center_rank,
        )
        if not rows:
            return self.replies.markdown_warn(event, "指定的排行范围无效。")
        if spec is None and highlight is None:
            return self.replies.markdown_warn(event, "本群军队不在前 1000 排行中。")
        await self._with_member_change(rows, prev_day=member_prev_day)
        return await self._send_rank(
            event,
            title=title,
            date_label=date_label,
            rows=rows,
            captured_at=captured_at,
            show_daily=True,
            score_label="周贡",
        )

    async def _live_union_snapshots(
        self,
        user,
        day: str,
        spec: tuple[int, int] | int | None,
        army_id: int,
        cache: list[UnionSnapshot],
    ) -> list[UnionSnapshot]:
        need = _spec_need(spec, 0)
        if need == 0:
            ref_rank = next(
                (
                    item.rank
                    for item in cache
                    if int(item.union_id) == int(army_id)
                ),
                None,
            )
            need = ref_rank + 10 if ref_rank else UNION_RANK_LIMIT
        limit = min(max(need, 10), UNION_RANK_LIMIT)
        cache_map = {item.union_id: item for item in cache}
        captured_at = datetime.now(timezone.utc).isoformat()

        while True:
            unions = await fetch_union_rank(user, limit)
            if not unions:
                return []
            items = []
            for union in unions:
                union_id = int(getattr(union, "id", 0) or 0)
                prev_item = cache_map.get(union_id)
                items.append(
                    UnionSnapshot(
                        snapshot_date=day,
                        rank=0,
                        union_id=union_id,
                        name=str(getattr(union, "name", "") or ""),
                        level=int(getattr(union, "level", 0) or 0),
                        members_num=int(getattr(union, "members_num", 0) or 0),
                        contribution=int(getattr(union, "contribution", 0) or 0),
                        today_contribution=(
                            prev_item.today_contribution if prev_item else None
                        ),
                        captured_at=captured_at,
                    )
                )
            if spec is not None or len(unions) >= UNION_RANK_LIMIT:
                return items
            if any(int(item.union_id) == int(army_id) for item in items):
                return items
            if limit >= UNION_RANK_LIMIT:
                return items
            limit = min(limit + 100, UNION_RANK_LIMIT)

    async def _with_member_change(
        self,
        rows: list[dict],
        prev_day: str | None = None,
    ) -> None:
        if prev_day is None:
            prev_day = (
                (datetime.now(SHANGHAI) - timedelta(days=2)).date().isoformat()
            )
        prev_map = {
            item.union_id: item
            for item in await self.store.list_union_snapshots(prev_day)
        }
        for row in rows:
            prev = prev_map.get(int(row["union_id"]))
            row["member_change"] = _member_change(row["members_num"], prev)

    async def _send_rank(
        self,
        event: AstrMessageEvent,
        *,
        title: str,
        date_label: str,
        rows: list[dict],
        captured_at: str,
        show_daily: bool = True,
        score_label: str | None = None,
    ) -> MessageEventResult:
        renderer = UnionRankRenderer()
        html = renderer.html(
            title=title,
            date_label=date_label,
            rows=rows,
            captured_at=_fmt_local(captured_at),
            show_daily=show_daily,
            score_label=score_label,
        )
        png = await renderer.to_png(html)
        return self.replies.image_result(event, png)
