from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bqyx_bot.models import MemberDaily, MemberSnapshot
from bqyx_bot.parsing import parse_year_month
from bqyx_bot.schedule import (
    as_shanghai,
    capture_date,
    compute_daily_from_snapshots,
)
from bqyx_bot.store import SqliteStore

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
    """验证 member_daily 与 member_snapshot 共享同一个 retention_days 环境变量并同步清理。"""
    store = SqliteStore(tmp_path / "test_prune.db", retention_days=2)
    await store.init()

    # 插入超期的旧数据与未超期的数据
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

    # 写入新快照时会触发 _prune_old_member_snapshots
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
    # 写入新日贡时会触发 _prune_old_member_daily
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

    # 验证 2020-01-01 的 snapshot 和 daily 均已被独立清理
    snaps_old = await store.list_member_snapshots_for_month(uid="u1", year=2020, month=1, army_id=1)
    dailies_old = await store.list_member_daily(uid="u1", year=2020, month=1, army_id=1)
    assert len(snaps_old) == 0
    assert len(dailies_old) == 0


def test_compute_daily_from_snapshots_2340_scenario():
    """验证 23:40 晚贡献 bug 通过 0点总贡献 差值算法得到完美修复。

    场景说明：
    - D 日(2026-09-01) 23:30 采集快照：累计总贡 10000，今日贡献 1000
      此时 D 日 0点总贡献 = 10000 - 1000 = 9000
    - 23:40 成员又刷了 500 贡献，实际总贡达到 10500，实际今日贡献为 1500
    - 00:00 游戏 0 点重置 conDay=0
    - D+1 日(2026-09-02) 成员当天刷了 200 贡献，23:30 快照：
      累计总贡 10700，今日贡献 200
      此时 D+1 日 0点总贡献 = 10700 - 200 = 10500
    - 算法计算 D 日真实日贡 = D+1日 0点总贡献 (10500) - D日 0点总贡献 (9000) = 1500！
      成功捕获了 23:30 之后的 500 晚贡献！
    """
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
    """验证 capture_date 严格使用上海自然日，不因午夜或凌晨回退到昨天。"""
    t_midnight = datetime(2026, 9, 24, 0, 5, tzinfo=SHANGHAI)
    assert capture_date(t_midnight) == "2026-09-24"

    t_morning = datetime(2026, 9, 24, 8, 30, tzinfo=SHANGHAI)
    assert capture_date(t_morning) == "2026-09-24"

    t_night = datetime(2026, 9, 24, 23, 30, tzinfo=SHANGHAI)
    assert capture_date(t_night) == "2026-09-24"


def test_shorthand_month_parsing():
    """验证年月解析支持简写月份如 9月、08月 等。"""
    ref = datetime(2026, 9, 24, 12, 0, tzinfo=SHANGHAI)
    assert parse_year_month("我的贡献 9月", default_now=ref) == (2026, 9)
    assert parse_year_month("我的贡献 08月", default_now=ref) == (2026, 8)
    assert parse_year_month("我的贡献 2026-08", default_now=ref) == (2026, 8)
    assert parse_year_month("我的贡献 2026年7月", default_now=ref) == (2026, 7)
    assert parse_year_month("我的贡献 上月", default_now=ref) == (2026, 8)


@pytest.mark.asyncio
async def test_lazy_compute_single_write_through(tmp_path):
    """测试「我的贡献」懒计算昨日真实 daily：
    第一次触发计算并持久化到 member_daily；再次查询直接命中 DB，不再计算/重复写入。
    """
    from bqyx_bot.handlers.query import QueryHandlers

    store = SqliteStore(tmp_path / "lazy_test.db")
    await store.init()
    await store.set_group_army("g1", 101)
    await store.set_user_bind("g1", "qq1", "u1", 0)

    # 设定基准时间为 2026-09-02 10:00 (上海时区)
    fixed_now = datetime(2026, 9, 2, 10, 0, tzinfo=SHANGHAI)

    # 存入 2026-09-01 (昨日) 快照
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

    # 模拟 API 实时拉取 (今日数据)
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

    class FakeMessage:
        text = "我的贡献"

    class FakeEvent:
        group_id = "g1"
        user_id = "qq1"
        message = FakeMessage()

    # 第一次查询：昨日 daily 尚未生成
    with patch("bqyx_bot.handlers.query.as_shanghai", return_value=fixed_now):
        await handlers.check_my_contribution_wall.__wrapped__.__wrapped__(handlers, FakeEvent())

    # 验证昨日 (2026-09-01) 真实 daily 已经被计算并写入库
    dailies_after_1st = await store.list_member_daily("u1", 2026, 9, army_id=101)
    assert len(dailies_after_1st) == 1
    assert dailies_after_1st[0].date == "2026-09-01"
    # 昨日 0点总贡献 = 10000 - 1000 = 9000
    # 今日 0点总贡献 = 11800 - 300 = 11500
    # 真实日贡 = 11500 - 9000 = 2500
    assert dailies_after_1st[0].daily_contribution == 2500

    # 第二次查询：监听 store.upsert_member_daily 是否被重复调用
    with patch("bqyx_bot.handlers.query.as_shanghai", return_value=fixed_now):
        with patch.object(store, "upsert_member_daily", wraps=store.upsert_member_daily) as mock_upsert:
            await handlers.check_my_contribution_wall.__wrapped__.__wrapped__(handlers, FakeEvent())
            # 此时昨日 daily 已存在，不应再次触发 upsert_member_daily
            mock_upsert.assert_not_called()
