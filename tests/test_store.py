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
