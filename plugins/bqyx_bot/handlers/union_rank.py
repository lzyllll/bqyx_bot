"""军队排行查询：昨日日贡排名 / 今日日贡排名 / 军队排行（图片渲染，高亮本军）。"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..context import BqyxServices
from ..errors import BotError
from ..hooks import error_reply, query_limit
from ..models import UnionSnapshot
from ..schedule import SHANGHAI, report_date
from ..union_rank_render import UnionRankRenderer
from .schedule import fetch_union_rank

# 以本军排名为中心，前后各取 20 名
RANK_WINDOW = 20


def _rank_rows(
    items: list[UnionSnapshot],
    value_key: str,
    army_id: int,
) -> tuple[list[dict], int | None]:
    """把榜单按 value_key 降序重排，返回展示行（±20 窗口）与本军展示排名。"""
    ranked = sorted(items, key=lambda item: int(getattr(item, value_key, 0) or 0), reverse=True)
    center = next(
        (i for i, item in enumerate(ranked) if int(item.union_id) == int(army_id)),
        None,
    )
    if center is None:
        return [], None
    start = max(0, center - RANK_WINDOW)
    end = min(len(ranked), center + RANK_WINDOW + 1)
    rows = []
    for pos in range(start, end):
        item = ranked[pos]
        rows.append(
            {
                "rank": pos + 1,
                "name": item.name,
                "members_num": item.members_num,
                "contribution": item.contribution,
                "today_contribution": item.today_contribution,
                "highlight": int(item.union_id) == int(army_id),
            }
        )
    return rows, center + 1


def _fmt_local(iso_utc: str) -> str:
    try:
        return datetime.fromisoformat(iso_utc).astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso_utc


class UnionRankHandlers(BqyxServices):
    @error_reply
    @query_limit
    @registrar.on_group_command("昨日日贡")
    async def yesterday_union_rank(self, event: GroupMessageEvent) -> None:
        """昨日日贡排名：读昨日快照的当日新增贡献。"""
        _, army_id = await self.require_army(str(event.group_id))
        day = report_date()
        snapshots = await self.store.list_union_snapshots(day)
        if not snapshots:
            raise BotError(f"还没有 {day} 的军队排行快照，请等今晚 23:59 采集后再试。")
        rows, highlight = _rank_rows(snapshots, "today_contribution", army_id)
        if highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        await self._send_rank(
            event,
            title="昨日日贡排名",
            date_label=day,
            rows=rows,
            captured_at=snapshots[0].captured_at,
        )

    @error_reply
    @query_limit
    @registrar.on_group_command("今日日贡")
    async def today_union_rank(self, event: GroupMessageEvent) -> None:
        """今日日贡排名：实时拉取当前数据，对比昨晚快照算当日新增。"""
        user, army_id = await self.require_army(str(event.group_id))
        day = report_date()
        prev_map = {
            item.union_id: item.contribution
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
                    today_contribution=max(contribution - prev, 0) if prev is not None else 0,
                    captured_at=captured_at,
                )
            )
        rows, highlight = _rank_rows(items, "today_contribution", army_id)
        if highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        await self._send_rank(
            event,
            title="今日日贡排名（实时）",
            date_label=day,
            rows=rows,
            captured_at=captured_at,
        )

    @error_reply
    @query_limit
    @registrar.on_group_command("军队排行")
    async def union_rank(self, event: GroupMessageEvent) -> None:
        """军队排行：最新快照按总贡献排序。"""
        _, army_id = await self.require_army(str(event.group_id))
        day = report_date()
        snapshots = await self.store.list_union_snapshots(day)
        if not snapshots:
            raise BotError(f"还没有 {day} 的军队排行快照，请等今晚 23:59 采集后再试。")
        rows, highlight = _rank_rows(snapshots, "contribution", army_id)
        if highlight is None:
            raise BotError("本群军队不在前 1000 排行中。")
        await self._send_rank(
            event,
            title="军队总贡献排行",
            date_label=day,
            rows=rows,
            captured_at=snapshots[0].captured_at,
        )

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
