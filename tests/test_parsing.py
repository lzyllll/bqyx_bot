from bqyx_bot.parsing import parse_format, parse_format_and_limit


def test_parse_format_from_command_text():
    assert parse_format("查成员 表格") == "表格"
    assert parse_format("查成员") == "图片"
    assert parse_format("军队信息 文本") == "文本"


def test_parse_limit_and_format_in_any_order():
    limit, fmt = parse_format_and_limit("查日贡 图片 900", default_limit=1100, default_format="文本")
    assert limit == 900
    assert fmt == "图片"

    limit, fmt = parse_format_and_limit("查日贡 图片", default_limit=1100, default_format="文本")
    assert limit == 1100
    assert fmt == "图片"
