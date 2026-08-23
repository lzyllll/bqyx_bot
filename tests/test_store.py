import pytest

from bqyx_bot.store import SqliteStore


@pytest.fixture
async def store(tmp_path):
    db = SqliteStore(tmp_path / "bqyx.db", retention_days=0)
    await db.init()
    return db


async def test_group_army_roundtrip(store):
    assert await store.get_group_army("100") is None
    await store.set_group_army("100", 88)
    assert await store.get_group_army("100") == 88
    await store.set_group_army("100", 99)
    assert await store.get_group_army("100") == 99


async def test_user_bind_includes_arch_index(store):
    await store.set_user_bind("100", "200", "5061", 4)
    bind = await store.get_user_bind("100", "200")
    assert bind is not None
    assert bind.uid == "5061"
    assert bind.arch_index == 4


async def test_merge_user_binds_counts(store):
    await store.set_user_bind("100", "1", "u1", 0)
    new, updated, unchanged = await store.merge_user_binds(
        "100",
        {
            "1": ("u1", 0),
            "2": ("u2", 3),
            "1b": ("u3", 1),
        },
    )
    # key "1" unchanged, "2" new, "1b" new. Wait "1" is unchanged, we also update "1" if we included different...
    assert unchanged == 1
    assert new == 2
    assert updated == 0


async def test_exclude_at_add_remove(store):
    assert await store.add_exclude("100", "200") is True
    assert await store.add_exclude("100", "200") is False
    assert await store.list_exclude("100") == ["200"]
    assert await store.remove_exclude("100", "200") is True
    assert await store.remove_exclude("100", "200") is False

async def test_list_group_armies(store):
    await store.set_group_army("100", 88)
    await store.set_group_army("200", 99)
    assert await store.list_group_armies() == [("100", 88), ("200", 99)]


async def test_member_snapshot_roundtrip(store):
    from bqyx_bot.models import MemberSnapshot

    items = [
        MemberSnapshot("100", 88, "2026-08-23", "u1", 0, "甲", 10000, 2100, 3000, "t1"),
        MemberSnapshot("100", 88, "2026-08-23", "u2", 1, "乙", 8000, 800, 1000, "t1"),
    ]
    await store.replace_member_snapshots("100", 88, "2026-08-23", items)
    loaded = await store.list_member_snapshots("100", "2026-08-23")
    assert [item.uid for item in loaded] == ["u1", "u2"]
    assert loaded[0].con_day == 2100
    assert loaded[0].contribution == 10000

    await store.replace_member_snapshots(
        "100",
        88,
        "2026-08-23",
        [MemberSnapshot("100", 88, "2026-08-23", "u3", 2, "丙", 10, 1, 1, "t2")],
    )
    loaded = await store.list_member_snapshots("100", "2026-08-23")
    assert [item.uid for item in loaded] == ["u3"]


async def test_snapshot_retention_prunes_old_days(tmp_path):
    from datetime import datetime, timedelta, timezone

    from bqyx_bot.models import MemberSnapshot

    shanghai = timezone(timedelta(hours=8))
    today = datetime.now(shanghai).date().isoformat()
    yesterday = (datetime.now(shanghai) - timedelta(days=1)).date().isoformat()
    old_day = (datetime.now(shanghai) - timedelta(days=5)).date().isoformat()

    store = SqliteStore(tmp_path / "ret.db", retention_days=3)
    await store.init()

    def snap(day, uid):
        return MemberSnapshot("100", 88, day, uid, 0, "n" + uid, 1, 1, 1, "t")

    await store.replace_member_snapshots("100", 88, old_day, [snap(old_day, "u0")])
    await store.replace_member_snapshots("100", 88, yesterday, [snap(yesterday, "u1")])
    await store.replace_member_snapshots("100", 88, today, [snap(today, "u2")])

    # 再次写入当天（模拟 23:30 采集），触发旧快照清理
    await store.replace_member_snapshots("100", 88, today, [snap(today, "u3")])

    assert await store.list_member_snapshots("100", old_day) == []
    assert [item.uid for item in await store.list_member_snapshots("100", yesterday)] == ["u1"]
    assert [item.uid for item in await store.list_member_snapshots("100", today)] == ["u3"]


async def test_snapshot_retention_disabled_keeps_all(tmp_path):
    from datetime import datetime, timedelta, timezone

    from bqyx_bot.models import MemberSnapshot

    shanghai = timezone(timedelta(hours=8))
    today = datetime.now(shanghai).date().isoformat()
    old_day = (datetime.now(shanghai) - timedelta(days=30)).date().isoformat()

    store = SqliteStore(tmp_path / "keep.db", retention_days=0)
    await store.init()

    def snap(day, uid):
        return MemberSnapshot("100", 88, day, uid, 0, "n" + uid, 1, 1, 1, "t")

    await store.replace_member_snapshots("100", 88, old_day, [snap(old_day, "u0")])
    await store.replace_member_snapshots("100", 88, today, [snap(today, "u1")])

    assert len(await store.list_member_snapshots("100", old_day)) == 1
    assert len(await store.list_member_snapshots("100", today)) == 1


async def test_list_member_snapshots_filters_by_army(tmp_path):
    """群改绑军队后，同群残留旧军队快照必须能被 army_id 过滤掉。"""
    from bqyx_bot.models import MemberSnapshot

    store = SqliteStore(tmp_path / "army.db", retention_days=0)
    await store.init()

    def snap(army_id, uid):
        return MemberSnapshot("g1", army_id, "2026-08-23", uid, 0, "n" + uid, 1, 1, 1, "t")

    await store.replace_member_snapshots("g1", 1241, "2026-08-23", [snap(1241, "old")])
    await store.replace_member_snapshots("g1", 29802, "2026-08-24", [snap(29802, "new")])

    # 不指定 army_id：同群同日期按覆盖语义只剩最后写入的一份
    assert [item.army_id for item in await store.list_member_snapshots("g1", "2026-08-23")] == [1241]
    assert [item.army_id for item in await store.list_member_snapshots("g1", "2026-08-24")] == [29802]

    # 指定 army_id：精确过滤
    assert await store.list_member_snapshots("g1", "2026-08-23", army_id=29802) == []
    assert [item.uid for item in await store.list_member_snapshots("g1", "2026-08-24", army_id=29802)] == ["new"]
    assert [item.uid for item in await store.list_member_snapshots("g1", "2026-08-23", army_id=1241)] == ["old"]


async def test_union_snapshot_roundtrip(store):
    from bqyx_bot.models import UnionSnapshot

    items = [
        UnionSnapshot("2026-08-23", 1, 1001, "甲军", 5, 120, 90000, 3000, "t1"),
        UnionSnapshot("2026-08-23", 2, 1002, "乙军", 4, 90, 80000, 2500, "t1"),
    ]
    await store.replace_union_snapshots("2026-08-23", items)
    loaded = await store.list_union_snapshots("2026-08-23")
    assert [(item.union_id, item.rank) for item in loaded] == [(1001, 1), (1002, 2)]
    assert loaded[0].today_contribution == 3000

    # 无基线（首次采集）时 today_contribution 存 None，读回后保持 None
    await store.replace_union_snapshots(
        "2026-08-24",
        [UnionSnapshot("2026-08-24", 1, 1001, "甲军", 5, 120, 91000, None, "t3")],
    )
    loaded_none = await store.list_union_snapshots("2026-08-24")
    assert loaded_none[0].today_contribution is None

    # 覆盖式写入同一天
    await store.replace_union_snapshots(
        "2026-08-23",
        [UnionSnapshot("2026-08-23", 1, 1003, "丙军", 3, 60, 50000, 1000, "t2")],
    )
    loaded = await store.list_union_snapshots("2026-08-23")
    assert [item.union_id for item in loaded] == [1003]


async def test_union_snapshot_retention_prunes_old_days(tmp_path):
    from datetime import datetime, timedelta, timezone

    from bqyx_bot.models import UnionSnapshot

    shanghai = timezone(timedelta(hours=8))
    today = datetime.now(shanghai).date().isoformat()
    old_day = (datetime.now(shanghai) - timedelta(days=5)).date().isoformat()

    store = SqliteStore(tmp_path / "uret.db", retention_days=3)
    await store.init()

    def row(day, uid):
        return UnionSnapshot(day, 1, uid, "n" + str(uid), 1, 10, 100, 10, "t")

    await store.replace_union_snapshots(old_day, [row(old_day, 1)])
    await store.replace_union_snapshots(today, [row(today, 2)])

    assert await store.list_union_snapshots(old_day) == []
    assert [item.union_id for item in await store.list_union_snapshots(today)] == [2]


async def test_union_snapshot_nullable_migration(tmp_path):
    """老库（today_contribution NOT NULL DEFAULT 0）init 后：列变可空，整日全 0 转 NULL。"""
    import sqlite3

    from bqyx_bot.models import UnionSnapshot

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE union_snapshot (
            snapshot_date TEXT NOT NULL,
            rank INTEGER NOT NULL,
            union_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 0,
            members_num INTEGER NOT NULL DEFAULT 0,
            contribution INTEGER NOT NULL DEFAULT 0,
            today_contribution INTEGER NOT NULL DEFAULT 0,
            captured_at TEXT NOT NULL,
            PRIMARY KEY (snapshot_date, union_id)
        )
        """
    )
    conn.execute(
        "INSERT INTO union_snapshot VALUES ('2026-08-22', 1, 1, '甲', 1, 10, 100, 0, 't')"
    )
    conn.execute(
        "INSERT INTO union_snapshot VALUES ('2026-08-22', 2, 2, '乙', 1, 10, 200, 0, 't')"
    )
    conn.execute(
        "INSERT INTO union_snapshot VALUES ('2026-08-23', 1, 1, '甲', 1, 10, 300, 200, 't')"
    )
    conn.commit()
    conn.close()

    store = SqliteStore(path, retention_days=0)
    await store.init()

    day22 = await store.list_union_snapshots("2026-08-22")
    assert [item.today_contribution for item in day22] == [None, None]  # 整日全 0 → NULL
    day23 = await store.list_union_snapshots("2026-08-23")
    assert day23[0].today_contribution == 200  # 有值的日期保留

    # 迁移后列可空，可写入 None
    await store.replace_union_snapshots(
        "2026-08-24",
        [UnionSnapshot("2026-08-24", 1, 1, "甲", 1, 10, 400, None, "t")],
    )
    loaded = await store.list_union_snapshots("2026-08-24")
    assert loaded[0].today_contribution is None
