import pytest

from bqyx_bot.store import SqliteStore


@pytest.fixture
async def store(tmp_path):
    db = SqliteStore(tmp_path / "bqyx.db")
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
