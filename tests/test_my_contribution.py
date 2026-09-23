from __future__ import annotations

import calendar
from pathlib import Path
import pytest

from bqyx_bot.config import Settings
from bqyx_bot.models import MemberSnapshot
from bqyx_bot.render import (
    MyContributionRenderer,
    UnionRankRenderer,
    build_month_grid,
    get_contribution_level,
)
from bqyx_bot.store import SqliteStore

OUTPUT_DIR = Path(__file__).parent / "output"


def test_contribution_level_rules():
    """测试日贡分级规则：
    - None 为无记录 (白色 none)
    - 0 为红色 (zero)
    - <= 600 为浅绿 (level-1)
    - <= 1310 为中绿 (level-2)
    - <= 1400 为深绿 (level-3)
    - > 1400 为最深绿 (level-4)
    """
    assert get_contribution_level(None) == "none"
    assert get_contribution_level(0) == "zero"
    assert get_contribution_level(1) == "level-1"
    assert get_contribution_level(600) == "level-1"
    assert get_contribution_level(601) == "level-2"
    assert get_contribution_level(1310) == "level-2"
    assert get_contribution_level(1311) == "level-3"
    assert get_contribution_level(1400) == "level-3"
    assert get_contribution_level(1401) == "level-4"
    assert get_contribution_level(2000) == "level-4"


def test_build_month_grid_september_2026():
    """测试 2026年9月 的月历网格生成。"""
    records = {
        "2026-09-01": 0,
        "2026-09-02": 500,
        "2026-09-03": 1310,
        "2026-09-04": 1400,
        "2026-09-05": 1600,
        # 2026-09-06 未记录 (None)
    }
    weeks, labels = build_month_grid(2026, 9, records)

    assert labels == ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    # 2026-09-01 是周二，第一周第一天（周一）不在本月内
    first_week = weeks[0]
    assert first_week.days[0].in_month is False
    assert first_week.days[1].in_month is True
    assert first_week.days[1].day_num == 1
    assert first_week.days[1].level == "zero"
    assert first_week.days[1].display_val == "0"

    # 9月2日：500贡献 -> level-1
    assert first_week.days[2].level == "level-1"
    assert first_week.days[2].display_val == "500"

    # 9月3日：1310贡献 -> level-2
    assert first_week.days[3].level == "level-2"
    assert first_week.days[3].display_val == "1310"

    # 9月4日：1400贡献 -> level-3
    assert first_week.days[4].level == "level-3"
    assert first_week.days[4].display_val == "1400"

    # 9月5日：1600贡献 -> level-4
    assert first_week.days[5].level == "level-4"
    assert first_week.days[5].display_val == "1600"

    # 9月6日：无记录 -> none
    assert first_week.days[6].level == "none"
    assert first_week.days[6].display_val == "—"


def test_renderer_html_generation():
    renderer = MyContributionRenderer()
    records = {
        "2026-09-01": 1400,
        "2026-09-02": 0,
        "2026-09-03": 600,
        "2026-09-04": 1310,
        "2026-09-05": 1500,
    }
    html = renderer.html(
        player_name="测试队长",
        year=2026,
        month=9,
        daily_records=records,
        captured_at="2026-09-23 15:30:00",
    )
    assert "测试队长 的贡献墙" in html
    assert "2026年9月" in html
    assert "github-icon" not in html
    assert "UID:" not in html
    assert "达标天数" not in html
    assert "cell-zero" in html
    assert "cell-level-1" in html
    assert "cell-level-2" in html
    assert "cell-level-3" in html
    assert "cell-level-4" in html
    assert "cell-none" in html


def test_union_rank_renderer_template_dir():
    renderer = UnionRankRenderer()
    assert renderer.template_dir.is_dir()
    assert (renderer.template_dir / "union_rank.j2").is_file()


def test_settings_retention_default_is_63():
    s = Settings(username="u", password="p", arch_index=0)
    assert s.snapshot_retention_days == 63


@pytest.mark.asyncio
async def test_store_retention_default_and_month_query(tmp_path):
    store = SqliteStore(tmp_path / "test.db")
    assert store.retention_days == 63
    await store.init()

    # 插入成员快照
    snap_day1 = MemberSnapshot(
        army_id=101,
        snapshot_date="2026-09-01",
        uid="user1",
        arch_index=0,
        nickname="玩家1",
        contribution=1000,
        con_day=1400,
        this_week=1400,
        captured_at="t1",
    )
    snap_day2 = MemberSnapshot(
        army_id=101,
        snapshot_date="2026-09-02",
        uid="user1",
        arch_index=0,
        nickname="玩家1",
        contribution=2400,
        con_day=0,
        this_week=1400,
        captured_at="t2",
    )
    snap_other_month = MemberSnapshot(
        army_id=101,
        snapshot_date="2026-08-31",
        uid="user1",
        arch_index=0,
        nickname="玩家1",
        contribution=500,
        con_day=500,
        this_week=500,
        captured_at="t0",
    )
    await store.replace_member_snapshots(101, "2026-09-01", [snap_day1])
    await store.replace_member_snapshots(101, "2026-09-02", [snap_day2])
    await store.replace_member_snapshots(101, "2026-08-31", [snap_other_month])

    # 按 2026-09 月查询
    month_snaps = await store.list_member_snapshots_for_month(
        uid="user1",
        year=2026,
        month=9,
        army_id=101,
    )
    assert len(month_snaps) == 2
    assert [s.snapshot_date for s in month_snaps] == ["2026-09-01", "2026-09-02"]
    assert month_snaps[0].con_day == 1400
    assert month_snaps[1].con_day == 0

    # 按 2026-08 月查询
    aug_snaps = await store.list_member_snapshots_for_month(
        uid="user1",
        year=2026,
        month=8,
        army_id=101,
    )
    assert len(aug_snaps) == 1
    assert aug_snaps[0].snapshot_date == "2026-08-31"


@pytest.mark.asyncio
async def test_my_contribution_render_to_png():
    """测试真实 Playwright 渲染转 PNG。"""
    renderer = MyContributionRenderer()
    records = {f"2026-09-{d:02d}": (1400 if d % 3 == 0 else (0 if d % 5 == 0 else 600)) for d in range(1, 24)}
    html = renderer.html(
        player_name="自动化测试玩家",
        uid="888888",
        year=2026,
        month=9,
        daily_records=records,
        army_name="先行者",
        captured_at="2026-09-23 15:30:00",
    )
    png = await renderer.to_png(html)
    assert len(png) > 1000
    assert png.startswith(b"\x89PNG")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / "test_my_contribution.png"
    out_file.write_bytes(png)
    assert out_file.exists()


@pytest.mark.asyncio
async def test_check_my_contribution_wall_handler(tmp_path):
    """测试 check_my_contribution_wall 指令处理流程。"""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock
    from bqyx_bot.handlers.query import QueryHandlers
    from bqyx_bot.models import UserBind

    store = SqliteStore(tmp_path / "handler_test.db")
    await store.init()
    await store.set_group_army("group_1", 101)
    await store.set_user_bind("group_1", "qq_1", "uid_1", 0)

    # 准备 member_snapshot
    await store.replace_member_snapshots(
        101,
        "2026-09-01",
        [
            MemberSnapshot(
                101,
                "2026-09-01",
                "uid_1",
                0,
                "玩家一号",
                1000,
                1400,
                1400,
                "t1",
            )
        ],
    )

    mock_user = AsyncMock()
    mock_member = SimpleNamespace(
        uid="uid_1",
        detail=SimpleNamespace(playerName="在线战神", conDay=1400),
    )
    mock_user.get_members.return_value = [mock_member]

    mock_account_service = AsyncMock()
    mock_account_service.get_user.return_value = mock_user

    mock_replies = AsyncMock()

    class FakeMessage:
        text = "我的贡献 2026-09"

    class FakeEvent:
        group_id = "group_1"
        user_id = "qq_1"
        message = FakeMessage()

        async def reply(self, *args, **kwargs):
            pass

    handlers = QueryHandlers()
    handlers.store = store
    handlers.account = mock_account_service
    handlers.replies = mock_replies

    await handlers.check_my_contribution_wall.__wrapped__.__wrapped__(handlers, FakeEvent())

    assert mock_replies.send_my_contribution_wall.called
    call_args = mock_replies.send_my_contribution_wall.call_args
    assert isinstance(call_args[0][1], bytes)
    assert call_args[0][1].startswith(b"\x89PNG")

