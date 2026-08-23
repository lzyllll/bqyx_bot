"""军队排行查询：昨日日贡排行 / 今日日贡排行 / 实时军队排行（图片渲染，高亮本军）。"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..context import BqyxServices
from ..errors import BotError
from ..hooks import error_reply, total_union_limit, union_live_limit, yesterday_union_limit
from ..models import UnionSnapshot
from ..schedule import SHANGHAI, report_date
from ..union_rank_render import UnionRankRenderer
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


def _member_change(current_members: int, prev: UnionSnapshot | None) -> str | None:
    """军队人数相对基线快照的变动标注；无变动或缺少基线返回 None。"""
    if prev is None:
        return None
    diff = int(current_members) - int(prev.members_num)
    if diff == 0:
        return None
    return f"+{diff}" if diff > 0 else str(diff)


def _contribution_change(current_contribution: int, prev: UnionSnapshot | None) -> str | None:
    """总贡献相对基线快照的变动标注；无变动或缺少基线返回 None。"""
    if prev is None:
        return None
    diff = int(current_contribution) - int(prev.contribution)
    if diff == 0:
        return None
    return f"+{diff}" if diff > 0 else str(diff)


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
    """把榜单按 value_key 降序重排，返回展示行与本军展示排行。

    center_rank 指定中心排行（1-based）；为 None 时以本军（army_id）为中心。
    window 会被限制在 MAX_WINDOW 以内。本军不在窗口内时 highlight 返回 None。
    """
    ranked = sorted(items, key=lambda item: int(getattr(item, value_key, 0) or 0), reverse=True)
    window = max(0, min(window, MAX_WINDOW))
    if center_rank is None:
        center_rank = next(
            (i + 1 for i, item in enumerate(ranked) if int(item.union_id) == int(army_id)),
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
        return datetime.fromisoformat(iso_utc).astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_utc


class UnionRankHandlers(BqyxServices):
    @error_reply
    @yesterday_union_limit
    @registrar.on_group_command("昨日日贡排行")
    async def yesterday_union_rank(self, event: GroupMessageEvent) -> None:
        """昨日日贡排行：读昨日快照的当日新增贡献。

        支持可选参数：'昨日日贡排行 90-110'（指定区间）或 '昨日日贡排行 100'（指定中心排行）。
        人数变动对比前天快照标注（利用 3 天保留窗口）。
        """
        _, army_id = await self.require_army(str(event.group_id))
        day = report_date()
        snapshots = await self.store.list_union_snapshots(day)
        if not snapshots:
            raise BotError(f"还没有 {day} 的军队排行快照，请等今晚 23:59 采集后再试。")
        # 昨日日贡 = 昨日快照的 today_contribution，需要前天快照做基线；
        # 没有前天数据（首次采集）时无法计算，整个榜单都不展示。
        if all(item.today_contribution is None for item in snapshots):
            raise BotError(f"没有 {day} 的前一天军队排行快照，昨日日贡暂无法计算，请等今晚采集后再试。")
        spec = parse_rank_range(event.message.text)
        center_rank, window = resolve_rank_spec(spec, len(snapshots))
        rows, highlight = _rank_rows(
            snapshots,
            "today_contribution",
            army_id,
            window=window,
            center_rank=center_rank,
        )
        if not rows:
            raise BotError("指定的排行范围无效。")
        if spec is None and highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        await self._with_member_change(rows)
        await self._send_rank(
            event,
            title="昨日日贡排行",
            date_label=day,
            rows=rows,
            captured_at=snapshots[0].captured_at,
        )

    @error_reply
    @union_live_limit
    @registrar.on_group_command("今日日贡排行")
    async def today_union_rank(self, event: GroupMessageEvent) -> None:
        """今日日贡排行：实时拉取当前数据，对比昨晚快照算当日新增。"""
        user, army_id = await self.require_army(str(event.group_id))
        day = report_date()
        prev_map = {
            item.union_id: item
            for item in await self.store.list_union_snapshots(day)
        }
        if not prev_map:
            raise BotError(f"还没有 {day} 的军队排行快照，请等今晚 23:59 采集后再试。")

        unions = await fetch_union_rank(user)
        if not unions:
            raise BotError("获取军队排行失败，请稍后再试。")
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
                    today_contribution=max(contribution - prev.contribution, 0) if prev is not None else None,
                    captured_at=captured_at,
                )
            )
        spec = parse_rank_range(event.message.text)
        center_rank, window = resolve_rank_spec(spec, len(items))
        rows, highlight = _rank_rows(
            items,
            "today_contribution",
            army_id,
            window=window,
            center_rank=center_rank,
        )
        if not rows:
            raise BotError("指定的排行范围无效。")
        if spec is None and highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        for row in rows:
            prev = prev_map.get(int(row["union_id"]))
            row["member_change"] = _member_change(row["members_num"], prev)
        await self._send_rank(
            event,
            title="今日日贡排行（实时）",
            date_label=day,
            rows=rows,
            captured_at=captured_at,
        )

    @error_reply
    @total_union_limit
    @registrar.on_group_command("实时军队排行")
    async def union_rank(self, event: GroupMessageEvent) -> None:
        """实时军队排行：实时拉取当前总贡献排行；昨晚快照仅作本军位置参考 cache（渐进扩大，上限 1000）。"""
        user, army_id = await self.require_army(str(event.group_id))
        day = report_date()
        spec = parse_rank_range(event.message.text)
        cache = await self.store.list_union_snapshots(day)
        snapshots = await self._live_union_snapshots(user, day, spec, army_id, cache)
        if not snapshots:
            raise BotError("获取军队排行失败，请稍后再试。")
        center_rank, window = resolve_rank_spec(spec, len(snapshots))
        rows, highlight = _rank_rows(
            snapshots,
            "contribution",
            army_id,
            window=window,
            center_rank=center_rank,
        )
        if not rows:
            raise BotError("指定的排行范围无效。")
        if spec is None and highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        await self._with_member_change(rows)
        # 较昨日：实时总贡献 − 昨晚快照总贡献
        prev_map = {item.union_id: item for item in cache}
        for row in rows:
            row["contribution_delta"] = _contribution_change(
                row["contribution"],
                prev_map.get(int(row["union_id"])),
            )
        await self._send_rank(
            event,
            title="军队总贡献排行",
            date_label=day,
            rows=rows,
            captured_at=snapshots[0].captured_at,
            show_daily=False,
        )

    async def _live_union_snapshots(
        self,
        user,
        day: str,
        spec: tuple[int, int] | int | None,
        army_id: int,
        cache: list[UnionSnapshot],
    ) -> list[UnionSnapshot]:
        """实时拉取军队排行（渐进扩大：先扩 10 再每次扩 100，上限 1000）。

        昨晚快照仅作参考 cache：本军模式用它估算本军位置（+10 起步），
        找不到本军再按页 100 扩大；指定范围模式直接按范围上界拉取。
        """
        need = _spec_need(spec, 0)
        if need == 0:
            ref_rank = next(
                (item.rank for item in cache if int(item.union_id) == int(army_id)),
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
                        today_contribution=prev_item.today_contribution if prev_item else None,
                        captured_at=captured_at,
                    )
                )
            if spec is not None or len(unions) >= UNION_RANK_LIMIT:
                # 指定范围：拉到范围上界即可；上限 1000 兜底
                return items
            if any(int(item.union_id) == int(army_id) for item in items):
                return items  # 本军已覆盖
            if limit >= UNION_RANK_LIMIT:
                return items
            limit = min(limit + 100, UNION_RANK_LIMIT)

    async def _with_member_change(self, rows: list[dict]) -> None:
        """为展示行注入人数变动标注（对比前天快照，利用 3 天保留窗口）。"""
        prev_day = (datetime.now(SHANGHAI) - timedelta(days=2)).date().isoformat()
        prev_map = {
            item.union_id: item
            for item in await self.store.list_union_snapshots(prev_day)
        }
        for row in rows:
            prev = prev_map.get(int(row["union_id"]))
            row["member_change"] = _member_change(row["members_num"], prev)

    async def _send_rank(
        self,
        event: GroupMessageEvent,
        *,
        title: str,
        date_label: str,
        rows: list[dict],
        captured_at: str,
        show_daily: bool = True,
    ) -> None:
        renderer = UnionRankRenderer()
        html = renderer.html(
            title=title,
            date_label=date_label,
            rows=rows,
            captured_at=_fmt_local(captured_at),
            show_daily=show_daily,
        )
        png = await renderer.to_png(html)
        b64_str = base64.b64encode(png).decode("utf-8")
        await self.api.qq.post_group_msg(
            group_id=event.group_id,
            image=f"base64://{b64_str}",
        )
