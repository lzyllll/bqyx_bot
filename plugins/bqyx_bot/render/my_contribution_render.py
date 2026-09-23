"""我的贡献（GitHub 贡献墙风格）图片渲染：Jinja2 模板 + Playwright 截图。"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .union_rank_render import TEMPLATE_DIR


def get_contribution_level(con: int | None) -> str:
    """根据贡献数值返回对应等级样式类：
    - None: "none" (无记录：白色)
    - 0: "zero" (贡献为0：红色)
    - <= 600: "level-1" (浅绿)
    - <= 1310: "level-2" (中绿)
    - <= 1400: "level-3" (深绿)
    - > 1400: "level-4" (最深绿)
    """
    if con is None:
        return "none"
    if con == 0:
        return "zero"
    if con <= 600:
        return "level-1"
    if con <= 1310:
        return "level-2"
    if con <= 1400:
        return "level-3"
    return "level-4"


@dataclass(frozen=True)
class DayCell:
    day_num: int
    date_str: str
    in_month: bool
    con: int | None
    level: str
    con_text: str
    display_val: str


@dataclass(frozen=True)
class WeekColumn:
    label: str
    days: list[DayCell]


def build_month_grid(
    year: int,
    month: int,
    daily_records: dict[str, int | None],
) -> tuple[list[WeekColumn], list[str]]:
    """组织当月周历数据（周一至周日）。"""
    cal = calendar.Calendar(firstweekday=0)
    month_weeks = cal.monthdays2calendar(year, month)
    weekday_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    weeks: list[WeekColumn] = []
    for idx, week_data in enumerate(month_weeks):
        days: list[DayCell] = []
        for day_num, _ in week_data:
            if day_num == 0:
                days.append(
                    DayCell(
                        day_num=0,
                        date_str="",
                        in_month=False,
                        con=None,
                        level="none",
                        con_text="",
                        display_val="",
                    )
                )
            else:
                date_str = f"{year:04d}-{month:02d}-{day_num:02d}"
                con = daily_records.get(date_str)
                level = get_contribution_level(con)
                if con is None:
                    display_val = "—"
                    con_text = "无记录"
                else:
                    display_val = str(con)
                    con_text = f"{con} 贡献"
                days.append(
                    DayCell(
                        day_num=day_num,
                        date_str=date_str,
                        in_month=True,
                        con=con,
                        level=level,
                        con_text=con_text,
                        display_val=display_val,
                    )
                )
        weeks.append(WeekColumn(label=f"第{idx + 1}周", days=days))

    return weeks, weekday_labels


class MyContributionRenderer:
    """把个人月度日贡数据渲染成 GitHub 贡献墙 HTML，并截图转为 PNG。"""

    def __init__(self, template_dir: Path | None = None) -> None:
        self.template_dir = Path(template_dir or TEMPLATE_DIR)
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "j2"]),
        )

    def html(
        self,
        *,
        player_name: str,
        year: int,
        month: int,
        daily_records: dict[str, int | None],
        uid: str | None = None,
        army_name: str | None = None,
        captured_at: str | None = None,
    ) -> str:
        weeks, weekday_labels = build_month_grid(year, month, daily_records)

        recorded_values = [v for v in daily_records.values() if v is not None]
        total_contribution = sum(recorded_values)
        recorded_days = len(recorded_values)
        perfect_days = sum(1 for v in recorded_values if v >= 1400)
        avg_contribution = (
            round(total_contribution / recorded_days) if recorded_days > 0 else 0
        )

        title = f"{player_name} 的贡献墙"
        month_label = f"{year}年{month}月"

        return self.env.get_template("my_contribution.j2").render(
            title=title,
            player_name=player_name,
            month_label=month_label,
            total_contribution=f"{total_contribution:,}",
            recorded_days=recorded_days,
            perfect_days=perfect_days,
            avg_contribution=f"{avg_contribution:,}",
            weekday_labels=weekday_labels,
            weeks=weeks,
            captured_at=captured_at,
        )

    async def to_png(self, html: str, viewport: tuple[int, int] = (562, 820)) -> bytes:
        from bqyx_api.utils.screenshot import html_to_png

        return await html_to_png(html, viewport=viewport)
