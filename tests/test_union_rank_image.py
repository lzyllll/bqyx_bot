from __future__ import annotations

from pathlib import Path
import pytest

from astrbot_plugin_bqyx.handlers.union_rank import _rank_rows
from astrbot_plugin_bqyx.models import UnionSnapshot
from astrbot_plugin_bqyx.render.union_rank_render import UnionRankRenderer

OUTPUT_DIR = Path(__file__).parent / "output"

DATE_LABEL = "2026-08-24"
CAPTURED_AT = "2026-08-24 23:59:58"
ARMY_CENTER = 50


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
    out_file = OUTPUT_DIR / filename
    out_file.write_bytes(png)
    return out_file


@pytest.mark.asyncio
async def test_render_daily_rank_center():
    items = _make_items()
    rows, _ = _rank_rows(
        items,
        "today_contribution",
        army_id=1000 + ARMY_CENTER,
        center_rank=ARMY_CENTER,
    )
    out = await _render(
        "今日日贡排行（实时）",
        rows,
        "rank_daily_today_center.png",
        show_daily=True,
    )
    assert out.exists()
    assert out.stat().st_size > 1000
