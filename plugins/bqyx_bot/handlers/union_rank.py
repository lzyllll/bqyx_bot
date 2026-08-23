"""军队排行查询：昨日日贡排名 / 今日日贡排名 / 军队排行（图片渲染，高亮本军）。"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta, timezone

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..context import BqyxServices
from ..errors import BotError
from ..hooks import error_reply, union_live_limit, union_snapshot_limit
from ..models import UnionSnapshot
from ..schedule import SHANGHAI, report_date
from ..union_rank_render import UnionRankRenderer
from .schedule import fetch_union_rank

# 默认以本军排名为中心，前后各取 6 名；可指定范围，但窗口上限 20
RANK_WINDOW = 6
MAX_WINDOW = 20


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
    """解析排名参数：'A-B' 区间 / 'N' 中心排名 / None（以本军为中心）。"""
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
    """把排名参数解析为（中心排名, 窗口）。count 为榜单总行数。"""
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
    """把榜单按 value_key 降序重排，返回展示行与本军展示排名。

    center_rank 指定中心排名（1-based）；为 None 时以本军（army_id）为中心。
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
    @union_snapshot_limit
    @registrar.on_group_command("昨日日贡")
    async def yesterday_union_rank(self, event: GroupMessageEvent) -> None:
        """昨日日贡排名：读昨日快照的当日新增贡献。

        支持可选参数：'昨日日贡 90-110'（指定区间）或 '昨日日贡 100'（指定中心排名）。
        人数变动对比前天快照标注（利用 3 天保留窗口）。
        """
        _, army_id = await self.require_army(str(event.group_id))
        day = report_date()
        snapshots = await self.store.list_union_snapshots(day)
        if not snapshots:
            raise BotError(f"还没有 {day} 的军队排行快照，请等今晚 23:59 采集后再试。")
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
            raise BotError("指定的排名范围无效。")
        if spec is None and highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        await self._with_member_change(rows)
        await self._send_rank(
            event,
            title="昨日日贡排名",
            date_label=day,
            rows=rows,
            captured_at=snapshots[0].captured_at,
        )

    @error_reply
    @union_live_limit
    @registrar.on_group_command("今日日贡")
    async def today_union_rank(self, event: GroupMessageEvent) -> None:
        """今日日贡排名：实时拉取当前数据，对比昨晚快照算当日新增。"""
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
                    today_contribution=max(contribution - prev.contribution, 0) if prev is not None else 0,
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
            raise BotError("指定的排名范围无效。")
        if spec is None and highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        for row in rows:
            prev = prev_map.get(int(row["union_id"]))
            row["member_change"] = _member_change(row["members_num"], prev)
        await self._send_rank(
            event,
            title="今日日贡排名（实时）",
            date_label=day,
            rows=rows,
            captured_at=captured_at,
        )

    @error_reply
    @union_snapshot_limit
    @registrar.on_group_command("军队排行")
    async def union_rank(self, event: GroupMessageEvent) -> None:
        """军队排行：最新快照按总贡献排序。支持 '军队排行 90-110' 或 '军队排行 100'。"""
        _, army_id = await self.require_army(str(event.group_id))
        day = report_date()
        snapshots = await self.store.list_union_snapshots(day)
        if not snapshots:
            raise BotError(f"还没有 {day} 的军队排行快照，请等今晚 23:59 采集后再试。")
        spec = parse_rank_range(event.message.text)
        center_rank, window = resolve_rank_spec(spec, len(snapshots))
        rows, highlight = _rank_rows(
            snapshots,
            "contribution",
            army_id,
            window=window,
            center_rank=center_rank,
        )
        if not rows:
            raise BotError("指定的排名范围无效。")
        if spec is None and highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        await self._with_member_change(rows, contribution_change=True)
        await self._send_rank(
            event,
            title="军队总贡献排行",
            date_label=day,
            rows=rows,
            captured_at=snapshots[0].captured_at,
        )

    async def _with_member_change(self, rows: list[dict], *, contribution_change: bool = False) -> None:
        """为展示行注入人数/贡献变动标注（对比前天快照，利用 3 天保留窗口）。"""
        prev_day = (datetime.now(SHANGHAI) - timedelta(days=2)).date().isoformat()
        prev_map = {
            item.union_id: item
            for item in await self.store.list_union_snapshots(prev_day)
        }
        for row in rows:
            prev = prev_map.get(int(row["union_id"]))
            row["member_change"] = _member_change(row["members_num"], prev)
            if contribution_change:
                row["contribution_change"] = _contribution_change(row["contribution"], prev)

    async def _send_rank(
        self,
        event: GroupMessageEvent,
        *,
        title: str,
        date_label: str,
        rows: list[dict],
        captured_at: str,
    ) -> None:
        renderer = UnionRankRenderer()
        html = renderer.html(
            title=title,
            date_label=date_label,
            rows=rows,
            captured_at=_fmt_local(captured_at),
        )
        png = await renderer.to_png(html)
        b64_str = base64.b64encode(png).decode("utf-8")
        await self.api.qq.post_group_msg(
            group_id=event.group_id,
            image=f"base64://{b64_str}",
        )
