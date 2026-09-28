from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from astrbot_plugin_bqyx.render import (
    HelpRenderer,
    get_help_asset_path,
    get_or_render_help_image,
)
from astrbot_plugin_bqyx.reply import ReplyService


def test_help_renderer_html_generation():
    renderer = HelpRenderer()
    html = renderer.html(update_time="2026-09-23 16:00")

    assert "BQYX Bot 帮助手册" in html
    assert "绑定游戏名" in html
    assert "我的贡献" in html
    assert "查物品 / 我的物品" in html
    assert "2026-09-23 16:00" in html

    # 用户要求：我的贡献不要提到 github
    assert "github" not in html.lower()


def test_help_asset_exists_and_is_valid_image():
    asset_path = get_help_asset_path()
    assert asset_path.name == "help.png"
    assert asset_path.exists()
    assert asset_path.stat().st_size > 1000  # valid image size


@pytest.mark.asyncio
async def test_get_or_render_help_image_loads_asset():
    data = await get_or_render_help_image()
    assert isinstance(data, bytes)
    assert len(data) > 1000
    # PNG signature check
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.asyncio
async def test_send_help_sends_image_reply():
    service = ReplyService(workspace=Path("."))
    event = MagicMock()

    results = await service.build_help(event)
    assert len(results) == 1
    assert results[0] is not None
