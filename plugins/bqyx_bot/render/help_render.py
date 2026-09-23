from __future__ import annotations

import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .union_rank_render import TEMPLATE_DIR


def get_help_asset_path() -> Path:
    """获取预生成的帮助图片持久化路径：plugins/bqyx_bot/assets/help.png"""
    return Path(__file__).resolve().parent.parent / "assets" / "help.png"


class HelpRenderer:
    """BQYX Bot 指令帮助手册图片渲染器：Jinja2 + Playwright 截图。"""

    def __init__(self, template_dir: Path | None = None) -> None:
        self.template_dir = Path(template_dir or TEMPLATE_DIR)
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "j2"]),
        )

    def html(self, *, update_time: str | None = None) -> str:
        cur_time = update_time or time.strftime("%Y-%m-%d %H:%M")
        return self.env.get_template("help.j2").render(
            update_time=cur_time,
        )

    async def to_png(
        self, html: str, viewport: tuple[int, int] = (780, 1500)
    ) -> bytes:
        from bqyx_api.utils.screenshot import html_to_png

        return await html_to_png(html, viewport=viewport)


async def render_help_image(
    output_path: Path | None = None,
    *,
    template_dir: Path | None = None,
) -> bytes:
    """使用 HTML 模板渲染帮助图片。若提供 output_path，则同步写入文件。"""
    renderer = HelpRenderer(template_dir=template_dir)
    html_content = renderer.html()
    png_bytes = await renderer.to_png(html_content)

    target_path = output_path or get_help_asset_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(png_bytes)

    return png_bytes


async def get_or_render_help_image() -> bytes:
    """获取帮助图片 bytes。若本地已有生成的静态图片，直接快速读取；否则实时生成并缓存。"""
    asset_path = get_help_asset_path()
    if asset_path.exists() and asset_path.stat().st_size > 0:
        return asset_path.read_bytes()

    return await render_help_image(asset_path)

