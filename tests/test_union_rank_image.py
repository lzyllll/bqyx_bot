"""图片输出测试：用模拟榜单数据渲染军队排行图，输出到 tests/output/。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dataclasses import replace

from bqyx_bot.handlers.union_rank import apply_weekly_contribution, _rank_rows
from bqyx_bot.models import UnionSnapshot
from bqyx_bot.union_rank_render import UnionRankRenderer

OUTPUT_DIR = Path(__file__).parent / "output"

DATE_LABEL = "2026-08-24"
CAPTURED_AT = "2026-08-24 23:59:58"
ARMY_CENTER = 50  # 本军在第 50 名，便于观察 ±20 窗口与高亮


def _make_items(count: int = 100) -> list[UnionSnapshot]:
    items = []
    for i in range(1, count + 1):
        items.append(
            UnionSnapshot(
                snapshot_date=DATE_LABEL,
                rank=i,
                union_id=1000 + i,
                name=f"军团-{i:03d}",
                level=(i % 7) + 1,
                members_num=60 + (i % 90),
                contribution=100000 - i * 500,
                today_contribution=5000 - i * 30,
                captured_at="2026-08-24T15:59:58+00:00",
            )
        )
    return items


async def _render(
    title: str,
    rows: list[dict],
    filename: str,
    *,
    show_daily: bool = True,
    score_label: str | None = None,
    date_label: str = DATE_LABEL,
) -> Path:
    renderer = UnionRankRenderer()
    html = renderer.html(
        title=title,
        date_label=date_label,
        rows=rows,
        captured_at=CAPTURED_AT,
        show_daily=show_daily,
        score_label=score_label,
    )
    png = await renderer.to_png(html)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / filename
    out.write_bytes(png)
    assert out.stat().st_size > 1000, f"{filename} 渲染结果过小"
    return out


@pytest.mark.asyncio
async def test_render_union_rank_images():
    items = _make_items()
    army_id = 1000 + ARMY_CENTER

    today_rows = _rank_rows(items, "today_contribution", army_id)[0]
    # 模拟今日成员变动：第 50 名 +3、第 48 名 -2，验证图片标注
    today_rows[6]["member_change"] = "+3"  # 50 名
    today_rows[4]["member_change"] = "-2"  # 48 名

    # 昨日日贡也标注（对比前天）：第 50 名 +5、第 47 名 -1
    yesterday_rows = _rank_rows(items, "today_contribution", army_id)[0]
    yesterday_rows[6]["member_change"] = "+5"
    yesterday_rows[3]["member_change"] = "-1"

    # 指定区间：以第 90 名为中心 ±10（窗口上限内）
    range_rows = _rank_rows(
        items,
        "contribution",
        army_id,
        center_rank=90,
        window=10,
    )[0]

    # 本周/上周周贡：相对周日基线的总贡献差，默认本军上下 6 名
    this_week_items = apply_weekly_contribution(
        items,
        {
            item.union_id: replace(
                item,
                contribution=item.contribution - (9000 - (item.union_id - 1000) * 40),
            )
            for item in items
        },
    )
    this_week_rows = _rank_rows(this_week_items, "today_contribution", army_id)[0]
    this_week_rows[6]["member_change"] = "+4"
    this_week_rows[2]["member_change"] = "-2"

    last_week_items = apply_weekly_contribution(
        items,
        {
            item.union_id: replace(
                item,
                contribution=item.contribution - (12000 - (item.union_id - 1000) * 60),
            )
            for item in items
        },
    )
    last_week_rows = _rank_rows(last_week_items, "today_contribution", army_id)[0]
    last_week_rows[6]["member_change"] = "+1"
    last_week_rows[8]["member_change"] = "-3"

    # 军队总贡献排行：注入人数与较昨日贡献变动标注
    total_rows = _rank_rows(items, "contribution", army_id)[0]
    total_rows[6]["member_change"] = "+2"
    total_rows[6]["contribution_delta"] = "+3200"  # 本军
    total_rows[3]["contribution_delta"] = "-1500"

    outputs = [
        await _render(
            "昨日日贡排行",
            yesterday_rows,
            "union_rank_yesterday.png",
        ),
        await _render(
            "今日日贡排行（实时）",
            today_rows,
            "union_rank_today.png",
        ),
        await _render(
            "军队总贡献排行",
            total_rows,
            "union_rank_total.png",
            show_daily=False,
        ),
        await _render(
            "军队总贡献排行（指定 80-100 名）",
            range_rows,
            "union_rank_range.png",
            show_daily=False,
        ),
        await _render(
            "本周周贡排行（实时）",
            this_week_rows,
            "union_rank_this_week.png",
            score_label="周贡",
            date_label="2026-08-24 ~ 2026-08-26",
        ),
        await _render(
            "上周周贡排行",
            last_week_rows,
            "union_rank_last_week.png",
            score_label="周贡",
            date_label="2026-08-17 ~ 2026-08-23",
        ),
    ]
    for path in outputs:
        assert path.exists(), f"缺少输出图片 {path}"
