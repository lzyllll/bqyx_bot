from types import SimpleNamespace
from unittest.mock import MagicMock

from astrbot_plugin_bqyx.parsing import parse_choice_index
from astrbot_plugin_bqyx.reply import (
    ReplyService,
    md_cmd_enter,
    md_cmd_example,
    md_cmd_input,
)


def test_md_cmd_helpers():
    tag_enter = md_cmd_enter("张三", "1")
    assert tag_enter == '<qqbot-cmd-enter text="1" show="张三" />'

    tag_input = md_cmd_input("/绑定军队", "绑定军队")
    assert tag_input == '<qqbot-cmd-input text="%E7%BB%91%E5%AE%9A%E5%86%9B%E9%98%9F%20" show="/绑定军队" reference="false" />'

    tag_choice = md_cmd_input("张三", "1")
    assert tag_choice == '<qqbot-cmd-input text="1" show="张三" reference="false" />'

    tag_cancel = md_cmd_input("取消", "取消")
    assert tag_cancel == '<qqbot-cmd-input text="%E5%8F%96%E6%B6%88" show="取消" reference="false" />'

    tag_ex = md_cmd_example("/绑定军队 1234", "绑定军队 1234")
    assert tag_ex == '<qqbot-cmd-input text="%E7%BB%91%E5%AE%9A%E5%86%9B%E9%98%9F%201234" show="/绑定军队 1234" reference="false" />'


def test_markdown_direct_parameter_generation(tmp_path):
    service = ReplyService(workspace=tmp_path)
    event = MagicMock()
    event.plain_result = MagicMock(side_effect=lambda text: SimpleNamespace(text=text, use_markdown=MagicMock()))
    event.make_result = MagicMock(side_effect=lambda: SimpleNamespace(message=lambda text: SimpleNamespace(text=text, use_markdown=MagicMock())))

    cmd_tag = md_cmd_input("/绑定军队", "绑定军队")
    ex_tag = md_cmd_example("/绑定军队 26490", "绑定军队 26490")
    result = service.markdown_tip(
        event,
        "请输入军队ID",
        f"{cmd_tag} `<军队ID>`",
        f"例如：{ex_tag}",
    )

    text = result.text
    assert "> 💡 **请输入军队ID**" in text
    assert f"> **用法**：{cmd_tag} `<军队ID>`" in text
    assert f"> 例如：{ex_tag}" in text


def test_markdown_warn_direct_parameter(tmp_path):
    service = ReplyService(workspace=tmp_path)
    event = MagicMock()
    event.plain_result = MagicMock(side_effect=lambda text: SimpleNamespace(text=text, use_markdown=MagicMock()))

    result = service.markdown_warn(event, "参数错误", "请检查输入格式")
    assert "> ⚠️ **参数错误**" in result.text
    assert "> 请检查输入格式" in result.text


def test_parse_choice_index_extended_inputs():
    assert parse_choice_index("1", max_count=5) == 1
    assert parse_choice_index("#2", max_count=5) == 2
    assert parse_choice_index("/3", max_count=5) == 3
    assert parse_choice_index("4号", max_count=5) == 4
    assert parse_choice_index("第5个", max_count=5) == 5
    assert parse_choice_index("选择2", max_count=5) == 2
    assert parse_choice_index("绑定1", max_count=5) == 1
    assert parse_choice_index("99", max_count=5) is None
