from bqyx_bot.handlers.union_rank import RANK_WINDOW, _member_change, _rank_rows
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
