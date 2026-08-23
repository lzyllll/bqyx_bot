"""图片输出测试：用模拟榜单数据渲染三张军队排行图，输出到 tests/output/。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bqyx_bot.handlers.union_rank import _rank_rows
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


async def _render(title: str, rows: list[dict], filename: str) -> Path:
    renderer = UnionRankRenderer()
    html = renderer.html(
        title=title,
        date_label=DATE_LABEL,
        rows=rows,
        captured_at=CAPTURED_AT,
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

    outputs = [
        await _render(
            "昨日日贡排名",
            _rank_rows(items, "today_contribution", army_id)[0],
            "union_rank_yesterday.png",
        ),
        await _render(
            "今日日贡排名（实时）",
            today_rows,
            "union_rank_today.png",
        ),
        await _render(
            "军队总贡献排行",
            _rank_rows(items, "contribution", army_id)[0],
            "union_rank_total.png",
        ),
    ]
    for path in outputs:
        assert path.exists(), f"缺少输出图片 {path}"
