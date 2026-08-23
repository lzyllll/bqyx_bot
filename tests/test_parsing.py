from bqyx_bot.parsing import extract_uid, parse_format, parse_format_and_limit


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


def test_extract_uid_from_digits_or_suffix():
    assert extract_uid("123456") == "123456"
    assert extract_uid("123456_a") == "123456"
    assert extract_uid("123456_A") == "123456"
    assert extract_uid("UID:123456_a") == "123456"
    assert extract_uid("绑定uid 123456 4") == "123456"
    assert extract_uid("abc") is None
    assert extract_uid("") is None
