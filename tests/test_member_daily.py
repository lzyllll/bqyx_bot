from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from astrbot_plugin_bqyx.models import MemberDaily, MemberSnapshot
from astrbot_plugin_bqyx.parsing import parse_year_month
from astrbot_plugin_bqyx.schedule import (
    as_shanghai,
    capture_date,
    compute_daily_from_snapshots,
)
from astrbot_plugin_bqyx.store import SqliteStore

SHANGHAI = timezone(timedelta(hours=8))


@pytest.mark.asyncio
async def test_member_daily_crud(tmp_path):
    store = SqliteStore(tmp_path / "test_daily.db", retention_days=63)
    await store.init()

    # 1. 批量插入
    items = [
        MemberDaily(
            army_id=101,
            date="2026-09-01",
            uid="user1",
            nickname="玩家1",
            daily_contribution=1400,
            end_of_day_total=10000,
            computed_at="2026-09-02T00:00:00Z",
        ),
        MemberDaily(
            army_id=101,
            date="2026-09-02",
            uid="user1",
            nickname="玩家1_改名",
            daily_contribution=1500,
            end_of_day_total=11500,
            computed_at="2026-09-03T00:00:00Z",
        ),
    ]
    await store.upsert_member_daily(items)

    # 2. 查询月份
    dailies = await store.list_member_daily(uid="user1", year=2026, month=9, army_id=101)
    assert len(dailies) == 2
    assert dailies[0].daily_contribution == 1400
    assert dailies[1].daily_contribution == 1500
    assert dailies[1].nickname == "玩家1_改名"

    # 3. 覆盖更新 (upsert)
    updated = [
        MemberDaily(
            army_id=101,
            date="2026-09-02",
            uid="user1",
            nickname="玩家1_最新",
            daily_contribution=1600,
            end_of_day_total=11600,
            computed_at="2026-09-03T01:00:00Z",
        )
    ]
    await store.upsert_member_daily(updated)
    dailies_after = await store.list_member_daily(uid="user1", year=2026, month=9, army_id=101)
    assert len(dailies_after) == 2
    assert dailies_after[1].daily_contribution == 1600
    assert dailies_after[1].nickname == "玩家1_最新"

    # 4. 查询已存在日期的集合
    dates = await store.list_member_daily_dates(101, "2026-09-01", "2026-09-03")
    assert dates == {"2026-09-01", "2026-09-02"}


@pytest.mark.asyncio
async def test_member_daily_pruning_shares_retention(tmp_path):
    store = SqliteStore(tmp_path / "test_prune.db", retention_days=2)
    await store.init()

    old_snap = MemberSnapshot(
        army_id=1,
        snapshot_date="2020-01-01",
        uid="u1",
        arch_index=0,
        nickname="老玩家",
        contribution=1000,
        con_day=500,
        this_week=500,
        captured_at="t0",
    )
    old_daily = MemberDaily(
        army_id=1,
        date="2020-01-01",
        uid="u1",
        nickname="老玩家",
        daily_contribution=500,
        end_of_day_total=1000,
        computed_at="t0",
    )
    recent_snap = MemberSnapshot(
        army_id=1,
        snapshot_date="2026-09-24",
        uid="u1",
        arch_index=0,
        nickname="老玩家",
        contribution=2000,
        con_day=1000,
        this_week=1000,
        captured_at="t1",
    )
    recent_daily = MemberDaily(
        army_id=1,
        date="2026-09-24",
        uid="u1",
        nickname="老玩家",
        daily_contribution=1000,
        end_of_day_total=2000,
        computed_at="t1",
    )

    await store.replace_member_snapshots(1, "2020-01-01", [old_snap])
    await store.upsert_member_daily([old_daily])
    await store.replace_member_snapshots(1, "2026-09-24", [recent_snap])
    await store.upsert_member_daily([recent_daily])

    now_today = as_shanghai().date().isoformat()
    await store.replace_member_snapshots(
        1,
        now_today,
        [
            MemberSnapshot(
                army_id=1,
                snapshot_date=now_today,
                uid="u1",
                arch_index=0,
                nickname="老玩家",
                contribution=3000,
                con_day=1000,
                this_week=1000,
                captured_at="now",
            )
        ],
    )
    await store.upsert_member_daily(
        [
            MemberDaily(
                army_id=1,
                date=now_today,
                uid="u1",
                nickname="老玩家",
                daily_contribution=1000,
                end_of_day_total=3000,
                computed_at="now",
            )
        ]
    )

    snaps_old = await store.list_member_snapshots_for_month(uid="u1", year=2020, month=1, army_id=1)
    dailies_old = await store.list_member_daily(uid="u1", year=2020, month=1, army_id=1)
    assert len(snaps_old) == 0
    assert len(dailies_old) == 0


def test_compute_daily_from_snapshots_2340_scenario():
    snap_d = MemberSnapshot(
        army_id=101,
        snapshot_date="2026-09-01",
        uid="u_warrior",
        arch_index=0,
        nickname="夜猫子",
        contribution=10000,
        con_day=1000,
        this_week=1000,
        captured_at="2026-09-01T23:30:00",
    )
    snap_d_plus_1 = MemberSnapshot(
        army_id=101,
        snapshot_date="2026-09-02",
        uid="u_warrior",
        arch_index=0,
        nickname="夜猫子",
        contribution=10700,
        con_day=200,
        this_week=1200,
        captured_at="2026-09-02T23:30:00",
    )

    dailies = compute_daily_from_snapshots(
        previous_items=[snap_d],
        current_items=[snap_d_plus_1],
        target_date="2026-09-01",
    )

    assert len(dailies) == 1
    daily = dailies[0]
    assert daily.date == "2026-09-01"
    assert daily.daily_contribution == 1500
    assert daily.end_of_day_total == 10700


def test_capture_date_strict_today():
    t_midnight = datetime(2026, 9, 24, 0, 5, tzinfo=SHANGHAI)
    assert capture_date(t_midnight) == "2026-09-24"

    t_morning = datetime(2026, 9, 24, 8, 30, tzinfo=SHANGHAI)
    assert capture_date(t_morning) == "2026-09-24"

    t_night = datetime(2026, 9, 24, 23, 30, tzinfo=SHANGHAI)
    assert capture_date(t_night) == "2026-09-24"


def test_shorthand_month_parsing():
    ref = datetime(2026, 9, 24, 12, 0, tzinfo=SHANGHAI)
    assert parse_year_month("我的贡献 9月", default_now=ref) == (2026, 9)
    assert parse_year_month("我的贡献 08月", default_now=ref) == (2026, 8)
    assert parse_year_month("我的贡献 2026-08", default_now=ref) == (2026, 8)
    assert parse_year_month("我的贡献 2026年7月", default_now=ref) == (2026, 7)
    assert parse_year_month("我的贡献 上月", default_now=ref) == (2026, 8)


@pytest.mark.asyncio
async def test_lazy_compute_single_write_through(tmp_path):
    from astrbot_plugin_bqyx.handlers.query import QueryHandlers

    store = SqliteStore(tmp_path / "lazy_test.db")
    await store.init()
    await store.set_group_army("g1", 101)
    await store.set_user_bind("g1", "qq1", "u1", 0)

    fixed_now = datetime(2026, 9, 2, 10, 0, tzinfo=SHANGHAI)

    await store.replace_member_snapshots(
        101,
        "2026-09-01",
        [
            MemberSnapshot(
                army_id=101,
                snapshot_date="2026-09-01",
                uid="u1",
                arch_index=0,
                nickname="神枪手",
                contribution=10000,
                con_day=1000,
                this_week=1000,
                captured_at="t1",
            )
        ],
    )

    mock_user = AsyncMock()
    mock_member = SimpleNamespace(
        uid="u1",
        index=0,
        nickname="神枪手",
        contribution=11800,
        detail=SimpleNamespace(playerName="神枪手", conDay=300, conObj=SimpleNamespace(this_week=1800)),
    )
    mock_user.get_members.return_value = [mock_member]

    mock_account = AsyncMock()
    mock_account.get_user.return_value = mock_user

    mock_replies = AsyncMock()

    handlers = QueryHandlers()
    handlers.store = store
    handlers.account = mock_account
    handlers.replies = mock_replies

    class FakeEvent:
        def __init__(self):
            self.message_str = "我的贡献"
            self.message_obj = SimpleNamespace(message=[])

        def get_group_id(self):
            return "g1"

        def get_sender_id(self):
            return "qq1"

    # Unwrap decorators down to underlying function
    fn = handlers.check_my_contribution_wall
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    async def _invoke():
        res = fn(handlers, FakeEvent())
        if hasattr(res, "__anext__"):
            async for _ in res:
                pass
        else:
            await res

    with patch("astrbot_plugin_bqyx.handlers.query.as_shanghai", return_value=fixed_now):
        await _invoke()

    dailies_after_1st = await store.list_member_daily("u1", 2026, 9, army_id=101)
    assert len(dailies_after_1st) == 1
    assert dailies_after_1st[0].date == "2026-09-01"
    assert dailies_after_1st[0].daily_contribution == 2500

    with patch("astrbot_plugin_bqyx.handlers.query.as_shanghai", return_value=fixed_now):
        with patch.object(store, "upsert_member_daily", wraps=store.upsert_member_daily) as mock_upsert:
            await _invoke()
            mock_upsert.assert_not_called()
