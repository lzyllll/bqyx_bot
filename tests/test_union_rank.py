from types import SimpleNamespace

import pytest

from astrbot_plugin_bqyx.handlers.union_rank import (
    MAX_WINDOW,
    RANK_WINDOW,
    _contribution_change,
    _member_change,
    _rank_rows,
    _spec_need,
    apply_weekly_contribution,
    parse_rank_range,
    resolve_rank_spec,
)
from astrbot_plugin_bqyx.models import UnionSnapshot


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
    assert highlight == 2
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert [row["name"] for row in rows] == ["2", "3", "1"]
    assert [row["highlight"] for row in rows] == [False, True, False]


def test_rank_rows_window_around_center():
    items = [_row(i, i * 10, i) for i in range(1, 100)]
    rows, highlight = _rank_rows(items, "today_contribution", army_id=50)
    assert highlight == 50
    assert rows[0]["rank"] == 50 - RANK_WINDOW
    assert rows[-1]["rank"] == 50 + RANK_WINDOW
    assert len(rows) == RANK_WINDOW * 2 + 1


def test_rank_rows_clamps_at_edges():
    items = [_row(i, i * 10, 100 - i) for i in range(1, 100)]
    rows, highlight = _rank_rows(items, "today_contribution", army_id=2)
    assert highlight == 2
    assert rows[0]["rank"] == 1
    assert len(rows) == 2 + RANK_WINDOW


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
    assert parse_rank_range("实时军队排行 100") == 100
    assert parse_rank_range("昨日日贡") is None
    assert parse_rank_range("实时军队排行 abc") is None


def test_resolve_rank_spec():
    assert resolve_rank_spec((90, 110), 1000) == (100, 10)
    assert resolve_rank_spec((1, 1000), 1000) == (500, MAX_WINDOW)
    assert resolve_rank_spec(100, 1000) == (100, RANK_WINDOW)
    assert resolve_rank_spec(None, 1000) == (None, RANK_WINDOW)
    assert resolve_rank_spec((10, 3), 1000) == (6, 4)
    assert resolve_rank_spec((9999, 10001), 50) == (50, 0)


def test_rank_rows_specified_range():
    items = [_row(i, i * 10, i) for i in range(1, 101)]
    rows, highlight = _rank_rows(
        items,
        "today_contribution",
        army_id=9999,
        center_rank=90,
        window=10,
    )
    assert rows[0]["rank"] == 80
    assert rows[-1]["rank"] == 100
    assert len(rows) == 21
    assert highlight is None


def test_rank_rows_window_capped_at_max():
    items = [_row(i, i * 10, i) for i in range(1, 101)]
    rows, highlight = _rank_rows(
        items,
        "today_contribution",
        army_id=50,
        center_rank=50,
        window=999,
    )
    assert len(rows) == MAX_WINDOW * 2 + 1
    assert rows[0]["rank"] == 50 - MAX_WINDOW
    assert rows[-1]["rank"] == 50 + MAX_WINDOW


def test_spec_need():
    assert _spec_need((90, 110), 5) == 110
    assert _spec_need(100, 5) == 100
    assert _spec_need(None, 5) == 5


class FakeUnionUser:
    def __init__(self, count: int) -> None:
        self.count = count

    async def get_union_list(self, page_num: int, page_size: int):
        start = (page_num - 1) * page_size
        end = min(start + page_size, self.count)
        if start >= self.count:
            return SimpleNamespace(unions=[], count=self.count)
        unions = [
            SimpleNamespace(
                id=1000 + i,
                name=f"u{i}",
                level=1,
                members_num=10,
                contribution=10000 - i,
            )
            for i in range(start, end)
        ]
        return SimpleNamespace(unions=unions, count=self.count)


@pytest.mark.asyncio
async def test_fetch_union_rank_respects_limit():
    from astrbot_plugin_bqyx.handlers.schedule import fetch_union_rank

    user = FakeUnionUser(1500)
    got = await fetch_union_rank(user, limit=210)
    assert len(got) == 210
    assert got[0].id == 1000

    capped = await fetch_union_rank(user, limit=99999)
    assert len(capped) == 1000

    default = await fetch_union_rank(user)
    assert len(default) == 1000


def test_parse_rank_range_weekly_commands():
    assert parse_rank_range("本周周贡排行 90-110") == (90, 110)
    assert parse_rank_range("上周周贡排行 100") == 100
    assert parse_rank_range("本周周贡排行") is None
    assert parse_rank_range("本周周贡 90-110") == (90, 110)
    assert parse_rank_range("上周周贡 100") == 100


def test_apply_weekly_contribution_uses_baseline_diff():
    current = [
        _row(1, contribution=12000, today_contribution=None),
        _row(2, contribution=8000, today_contribution=None),
        _row(3, contribution=5000, today_contribution=None),
    ]
    baseline = {
        1: _row(1, contribution=10000),
        2: _row(2, contribution=8000),
    }
    items = apply_weekly_contribution(current, baseline)
    by_id = {item.union_id: item.today_contribution for item in items}
    assert by_id[1] == 2000
    assert by_id[2] == 0
    assert by_id[3] is None


def test_weekly_rank_window_centers_on_bound_army():
    current = [_row(i, contribution=10000 + i, today_contribution=None) for i in range(1, 40)]
    baseline = {i: _row(i, contribution=10000) for i in range(1, 40)}
    items = apply_weekly_contribution(current, baseline)
    rows, highlight = _rank_rows(items, "today_contribution", army_id=20)
    assert highlight == 20
    assert rows[0]["rank"] == 20 - RANK_WINDOW
    assert rows[-1]["rank"] == 20 + RANK_WINDOW
    assert len(rows) == RANK_WINDOW * 2 + 1
    assert rows[RANK_WINDOW]["union_id"] == 20


def test_renderer_score_label_weekly():
    from bqyx_api.render import UnionRankRenderer

    html = UnionRankRenderer().html(
        title="本周周贡排行（实时）",
        date_label="2026-08-24 ~ 2026-08-26",
        rows=[
            {
                "rank": 1,
                "union_id": 20,
                "name": "本军",
                "contribution": 12000,
                "today_contribution": 2000,
                "highlight": True,
                "members_num": 10,
                "member_change": "+1",
            }
        ],
        captured_at="t",
        score_label="周贡",
    )
    assert "周贡" in html
    assert "日贡" not in html
    assert "本军" in html


from unittest.mock import AsyncMock, MagicMock
from astrbot_plugin_bqyx.handlers.union_rank import UnionRankHandlers
from astrbot_plugin_bqyx.reply import ReplyService
from astrbot_plugin_bqyx.errors import GroupOnlyError, ParamError


class FakeEvent:
    def __init__(self, group_id: str = "1001", user_id: str = "456", message: str = ""):
        self.gid = str(group_id)
        self.uid = str(user_id)
        self.message_str = message

    def get_group_id(self) -> str:
        return self.gid

    def get_sender_id(self) -> str:
        return self.uid

    def plain_result(self, text: str):
        return SimpleNamespace(type="plain", text=text)


class DummyUnionRankService(UnionRankHandlers):
    def __init__(self, tmp_path):
        self.store = MagicMock()
        self._template_map = {}
        self.store.get_group_template = AsyncMock(side_effect=lambda gid: self._template_map.get(gid))

        async def _set(gid, style):
            self._template_map[gid] = style

        self.store.set_group_template = AsyncMock(side_effect=_set)
        self.store.record_command_call = AsyncMock()
        self.replies = ReplyService(tmp_path)


@pytest.mark.asyncio
async def test_switch_template(tmp_path):
    service = DummyUnionRankService(tmp_path)

    # 1. 初始状态查询当前模板
    event = FakeEvent(group_id="1001", message="切换模板")
    results = [res async for res in service.switch_template(event, style="")]
    assert len(results) == 1
    assert "当前群模板风格为：默认风格 (default)" in results[0].text

    # 2. 切换为经典风格
    event_classic = FakeEvent(group_id="1001", message="切换模板 经典")
    results_classic = [res async for res in service.switch_template(event_classic, style="经典")]
    assert len(results_classic) == 1
    assert "本群模板已成功切换为：经典风格 (classic)" in results_classic[0].text
    assert await service.store.get_group_template("1001") == "classic"

    # 3. 再次查询为经典风格
    event_check = FakeEvent(group_id="1001", message="切换模板")
    results_check = [res async for res in service.switch_template(event_check, style="")]
    assert "当前群模板风格为：经典风格 (classic)" in results_check[0].text

    # 4. 切换为默认风格
    event_default = FakeEvent(group_id="1001", message="切换模板 default")
    results_default = [res async for res in service.switch_template(event_default, style="default")]
    assert "本群模板已成功切换为：默认风格 (default)" in results_default[0].text
    assert await service.store.get_group_template("1001") == "default"

    # 5. 不支持的风格
    event_err = FakeEvent(group_id="1001", message="切换模板 cyberpunk")
    results_err = [res async for res in service.switch_template(event_err, style="cyberpunk")]
    assert len(results_err) == 1
    assert "不支持的模板风格「cyberpunk」" in results_err[0].text

    # 6. 私聊使用应提示仅群聊支持
    event_private = FakeEvent(group_id="", message="切换模板")
    results_priv = [res async for res in service.switch_template(event_private, style="")]
    assert len(results_priv) == 1
    assert "仅支持在群聊中使用" in results_priv[0].text


@pytest.mark.asyncio
async def test_send_rank_passes_group_style(tmp_path, monkeypatch):
    service = DummyUnionRankService(tmp_path)
    service._template_map["1001"] = "classic"

    captured_style = None

    class MockRenderer:
        def __init__(self, style=None):
            nonlocal captured_style
            captured_style = style

        def html(self, **kwargs):
            return "<html></html>"

        async def to_png(self, html):
            return b"fake-png"

    monkeypatch.setattr("astrbot_plugin_bqyx.handlers.union_rank.UnionRankRenderer", MockRenderer)

    event = FakeEvent(group_id="1001")
    await service._send_rank(
        event,
        title="今日日贡排行",
        date_label="2026-08-24",
        rows=[],
        captured_at="2026-08-24T12:00:00Z",
    )
    assert captured_style == "classic"
