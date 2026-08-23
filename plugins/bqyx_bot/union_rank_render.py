"""军队排行图片渲染：Jinja2 模板 + Playwright 截图。"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent / "templates"


class UnionRankRenderer:
    """把军队排行数据渲染成 HTML，再用 bqyx_api 的截图工具转成 PNG。"""

    def __init__(self, template_dir: Path | None = None) -> None:
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir or TEMPLATE_DIR)),
            autoescape=select_autoescape(["html", "j2"]),
        )

    def html(
        self,
        *,
        title: str,
        date_label: str,
        rows: list[dict],
        captured_at: str | None = None,
    ) -> str:
        return self.env.get_template("union_rank.j2").render(
            title=title,
            date_label=date_label,
            rows=rows,
            captured_at=captured_at,
        )

    async def to_png(self, html: str) -> bytes:
        from bqyx_api.utils.screenshot import html_to_png

        return await html_to_png(html)
