import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from astrbot_plugin_bqyx.reply import (
    HELP_MODULE_BIND,
    HELP_MODULE_PERSONAL,
    HELP_MODULE_RANK,
    HELP_MODULE_UNION,
    build_help_keyboard,
    normalize_help_module,
    ReplyService,
)
from astrbot_plugin_bqyx.qq.components import QQCKeyboard


def test_normalize_help_module():
    assert normalize_help_module("") == HELP_MODULE_BIND
    assert normalize_help_module("绑定") == HELP_MODULE_BIND
    assert normalize_help_module("账号绑定") == HELP_MODULE_BIND
    assert normalize_help_module("个人绑定") == HELP_MODULE_BIND

    assert normalize_help_module("个人") == HELP_MODULE_PERSONAL
    assert normalize_help_module("个人查询") == HELP_MODULE_PERSONAL
    assert normalize_help_module("查询") == HELP_MODULE_PERSONAL
    assert normalize_help_module("战力") == HELP_MODULE_PERSONAL

    assert normalize_help_module("军队") == HELP_MODULE_UNION
    assert normalize_help_module("军队查询") == HELP_MODULE_UNION
    assert normalize_help_module("军团") == HELP_MODULE_UNION
    assert normalize_help_module("本群查询") == HELP_MODULE_UNION

    assert normalize_help_module("排行") == HELP_MODULE_RANK
    assert normalize_help_module("排行榜") == HELP_MODULE_RANK
    assert normalize_help_module("实时排行") == HELP_MODULE_RANK


@pytest.mark.parametrize(
    "mod",
    [HELP_MODULE_BIND, HELP_MODULE_PERSONAL, HELP_MODULE_UNION, HELP_MODULE_RANK],
)
def test_build_help_keyboard_structure(mod):
    markdown_text, keyboard = build_help_keyboard(mod)

    assert isinstance(markdown_text, str)
    assert len(markdown_text) > 40
    assert isinstance(keyboard, QQCKeyboard)

    # 验证最大行数符合 QQ OpenAPI 规范（最多 5 行）
    assert 1 <= len(keyboard.rows) <= 5

    # 验证第 1 行是 4 列模块切换按钮（绑定、个人、军队、排行）
    switch_row = keyboard.rows[0]
    assert len(switch_row) == 4

    # 验证除第 1 行切换栏为 4 额外，其他行最多只能有 3 列
    for row_idx, row in enumerate(keyboard.rows[1:], start=2):
        assert 1 <= len(row) <= 3, f"第 {row_idx} 行按钮数量超过 3 列限制: {len(row)}"

    cmds = [btn.data for btn in switch_row]

    assert cmds == [
        "帮助 绑定",
        "帮助 个人",
        "帮助 军队",
        "帮助 排行",
    ]

    # 当前模块高亮（style=4），其余灰色（style=0）
    if mod == HELP_MODULE_BIND:
        assert switch_row[0].style == 4
        assert "📌" in switch_row[0].label
        assert switch_row[1].style == 0
        assert switch_row[2].style == 0
        assert switch_row[3].style == 0
    elif mod == HELP_MODULE_PERSONAL:
        assert switch_row[0].style == 0
        assert switch_row[1].style == 4
        assert "📌" in switch_row[1].label
        assert switch_row[2].style == 0
        assert switch_row[3].style == 0
    elif mod == HELP_MODULE_UNION:
        assert switch_row[0].style == 0
        assert switch_row[1].style == 0
        assert switch_row[2].style == 4
        assert "📌" in switch_row[2].label
        assert switch_row[3].style == 0
    elif mod == HELP_MODULE_RANK:
        assert switch_row[0].style == 0
        assert switch_row[1].style == 0
        assert switch_row[2].style == 0
        assert switch_row[3].style == 4
        assert "📌" in switch_row[3].label

    # 检查删除项：确认所有模块按钮中都不包含“一键绑定”、“免at列表”、“查成员 表格”
    all_btn_labels = [btn.label for row in keyboard.rows for btn in row]
    assert "一键绑定" not in all_btn_labels
    assert "免at列表" not in all_btn_labels
    assert "查成员 表格" not in all_btn_labels


@pytest.mark.asyncio
async def test_send_help_qq_official_keyboard_sent(tmp_path):
    service = ReplyService(workspace=tmp_path)
    event = MagicMock()

    with patch("astrbot_plugin_bqyx.qq.components.send_keyboard", new_callable=AsyncMock) as mock_send_kb:
        await service.send_help(event, module="军队查询")
        mock_send_kb.assert_awaited_once()

        call_kwargs = mock_send_kb.call_args[1]
        assert "markdown" in call_kwargs
        assert "keyboard" in call_kwargs
        assert "军队" in call_kwargs["markdown"]
