from bqyx_bot.handlers.union_rank import (
    MAX_WINDOW,
    RANK_WINDOW,
    _contribution_change,
    _member_change,
    _rank_rows,
    parse_rank_range,
    resolve_rank_spec,
)
from bqyx_bot.models import UnionSnapshot


def _row(union_id, contribution, today_contribution=0, name="", members_num=10):
    return UnionSnapshot(
        snapshot_date="2026-08-23",
        rank=0,
        union_id=union_id,
        name=name or str(union_id),
        level=1,
        members_num=members_num,
        contribution=contribution,
        today_contribution=today_contribution,
        captured_at="t",
    )


def test_rank_rows_sorts_by_value_key_and_highlights():
    items = [
        _row(1, 100, 5),
        _row(2, 300, 30),
        _row(3, 200, 20),
    ]
    rows, highlight = _rank_rows(items, "today_contribution", army_id=3)
    assert highlight == 2  # 按日贡降序：2(30) -> 3(20) -> 1(5)
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert [row["name"] for row in rows] == ["2", "3", "1"]
    assert [row["highlight"] for row in rows] == [False, True, False]


def test_rank_rows_window_around_center():
    items = [_row(i, i * 10, i) for i in range(1, 100)]  # 99 个军队
    rows, highlight = _rank_rows(items, "today_contribution", army_id=50)
    assert highlight == 50
    assert rows[0]["rank"] == 50 - RANK_WINDOW
    assert rows[-1]["rank"] == 50 + RANK_WINDOW
    assert len(rows) == RANK_WINDOW * 2 + 1


def test_rank_rows_clamps_at_edges():
    # 日贡与 uid 相反：uid 越小日贡越大，army_id=2 就在第 2 名
    items = [_row(i, i * 10, 100 - i) for i in range(1, 100)]
    rows, highlight = _rank_rows(items, "today_contribution", army_id=2)
    assert highlight == 2
    assert rows[0]["rank"] == 1  # 顶部截断
    assert len(rows) == 2 + RANK_WINDOW  # 1..22


def test_rank_rows_missing_army_returns_none():
    items = [_row(1, 100, 5), _row(2, 200, 20)]
    rows, highlight = _rank_rows(items, "today_contribution", army_id=999)
    assert rows == []
    assert highlight is None


def test_member_change_marks_diff_only():
    prev = _row(1, 100, 5, members_num=90)
    assert _member_change(93, prev) == "+3"
    assert _member_change(87, prev) == "-3"
    assert _member_change(90, prev) is None
    assert _member_change(90, None) is None


def test_contribution_change_marks_diff_only():
    prev = _row(1, contribution=10000, today_contribution=5)
    assert _contribution_change(10500, prev) == "+500"
    assert _contribution_change(9600, prev) == "-400"
    assert _contribution_change(10000, prev) is None
    assert _contribution_change(10000, None) is None


def test_parse_rank_range():
    assert parse_rank_range("今日日贡 90-110") == (90, 110)
    assert parse_rank_range("军队排行 100") == 100
    assert parse_rank_range("昨日日贡") is None
    assert parse_rank_range("军队排行 abc") is None


def test_resolve_rank_spec():
    assert resolve_rank_spec((90, 110), 1000) == (100, 10)
    assert resolve_rank_spec((1, 1000), 1000) == (500, MAX_WINDOW)  # 窗口 clamp 到 20
    assert resolve_rank_spec(100, 1000) == (100, RANK_WINDOW)
    assert resolve_rank_spec(None, 1000) == (None, RANK_WINDOW)
    assert resolve_rank_spec((10, 3), 1000) == (6, 4)  # 区间自动归一，窗口取较大侧
    assert resolve_rank_spec((9999, 10001), 50) == (50, 0)  # 越界 clamp 到榜单，退化为单行


def test_rank_rows_specified_range():
    items = [_row(i, i * 10, i) for i in range(1, 101)]
    rows, highlight = _rank_rows(
        items,
        "today_contribution",
        army_id=9999,  # 本军不在窗口
        center_rank=90,
        window=10,
    )
    assert rows[0]["rank"] == 80
    assert rows[-1]["rank"] == 100
    assert len(rows) == 21
    assert highlight is None  # 本军不在指定范围内不高亮


def test_rank_rows_window_capped_at_max():
    items = [_row(i, i * 10, i) for i in range(1, 101)]
    rows, highlight = _rank_rows(
        items,
        "today_contribution",
        army_id=50,
        center_rank=50,
        window=999,  # 超过上限
    )
    assert len(rows) == MAX_WINDOW * 2 + 1
    assert rows[0]["rank"] == 50 - MAX_WINDOW
    assert rows[-1]["rank"] == 50 + MAX_WINDOW
