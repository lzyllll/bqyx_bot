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
    # 纯数字，或 数字_数字（UID_存档），提取数字部分
    assert extract_uid("123456") == "123456"
    assert extract_uid("123456_1") == "123456"
    assert extract_uid("UID:123456_1") == "123456"
    assert extract_uid("绑定uid 123456") == "123456"
    assert extract_uid("绑定uid 123456_1") == "123456"
    assert extract_uid("绑定uid 123456 4") == "123456"
    assert extract_uid("123456_a") == "123456"
    assert extract_uid("abc") is None
    assert extract_uid("") is None


def test_extract_command_arg():
    from types import SimpleNamespace
    from bqyx_bot.parsing import extract_command_arg

    # Direct arg takes priority
    assert extract_command_arg("张三", None, ("绑定游戏名",)) == "张三"
    assert extract_command_arg("  李四  ", None, ("绑定游戏名",)) == "李四"

    # From event message text
    event = SimpleNamespace(message=SimpleNamespace(text="绑定游戏名 王五"))
    assert (
        extract_command_arg("", event, ("绑定游戏名", "绑定角色名")) == "王五"
    )

    event2 = SimpleNamespace(message=SimpleNamespace(text="绑定角色名   赵六  "))
    assert (
        extract_command_arg("", event2, ("绑定游戏名", "绑定角色名")) == "赵六"
    )

    # Empty
    event3 = SimpleNamespace(message=SimpleNamespace(text="绑定游戏名"))
    assert extract_command_arg("", event3, ("绑定游戏名",)) == ""
    assert extract_command_arg("", None, ("绑定游戏名",)) == ""


def test_parse_choice_index():
    from bqyx_bot.parsing import parse_choice_index

    assert parse_choice_index("1", max_count=5) == 1
    assert parse_choice_index("5", max_count=5) == 5
    assert parse_choice_index(" 3 ", max_count=5) == 3
    assert parse_choice_index("0", max_count=5) is None
    assert parse_choice_index("6", max_count=5) is None
    assert parse_choice_index("abc", max_count=5) is None
    assert parse_choice_index(None, max_count=5) is None
    assert parse_choice_index("", max_count=5) is None


def test_parse_year_month():
    from datetime import datetime
    from bqyx_bot.parsing import parse_year_month

    base_time = datetime(2026, 9, 23)

    assert parse_year_month("我的贡献", default_now=base_time) == (2026, 9)
    assert parse_year_month("我的贡献 2026-08", default_now=base_time) == (
        2026,
        8,
    )
    assert parse_year_month("我的贡献 2026/05", default_now=base_time) == (
        2026,
        5,
    )
    assert parse_year_month("我的贡献 2025年12月", default_now=base_time) == (
        2025,
        12,
    )
    assert parse_year_month("我的贡献 202607", default_now=base_time) == (
        2026,
        7,
    )
    assert parse_year_month("我的贡献 上月", default_now=base_time) == (
        2026,
        8,
    )
    assert parse_year_month("我的贡献 上个月", default_now=base_time) == (
        2026,
        8,
    )

    # Cross year for last month
    jan_time = datetime(2026, 1, 15)
    assert parse_year_month("我的贡献 上月", default_now=jan_time) == (2025, 12)

