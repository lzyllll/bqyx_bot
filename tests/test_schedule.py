from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from bqyx_bot.models import MemberSnapshot
from bqyx_bot.schedule import (
    YesterdayScore,
    below_limit,
    calculate_yesterday,
    capture_date,
    report_date,
    snapshot_from_member,
    yesterday_contribution,
)

TZ = timezone(timedelta(hours=8))


def _snap(**kwargs) -> MemberSnapshot:
    data = dict(
        group_id="g",
        army_id=1,
        snapshot_date="2026-08-23",
        uid="1",
        arch_index=0,
        nickname="甲",
        contribution=10000,
        con_day=1500,
        this_week=4000,
        captured_at="t",
    )
    data.update(kwargs)
    return MemberSnapshot(**data)


def test_capture_date_keeps_evening_on_same_day():
    now = datetime(2026, 8, 23, 23, 30, tzinfo=TZ)
    assert capture_date(now) == "2026-08-23"


def test_capture_date_after_midnight_stays_previous_day():
    now = datetime(2026, 8, 24, 0, 5, tzinfo=TZ)
    assert capture_date(now) == "2026-08-23"


def test_report_date_at_noon_is_yesterday():
    now = datetime(2026, 8, 24, 12, 0, tzinfo=TZ)
    assert report_date(now) == "2026-08-23"


def test_yesterday_uses_midnight_baselines():
    previous = _snap(contribution=10000, con_day=1500)
    current = _snap(contribution=12100, con_day=400)
    # (12100-400) - (10000-1500) = 11700 - 8500 = 3200
    assert yesterday_contribution(previous, current) == 3200


def test_calculate_yesterday_matches_uid_and_archive():
    previous = [
        _snap(uid="1", arch_index=0, nickname="甲", contribution=10000, con_day=1500),
        _snap(uid="2", arch_index=1, nickname="乙", contribution=8000, con_day=200),
    ]
    current = [
        _snap(uid="2", arch_index=1, nickname="乙", contribution=9000, con_day=100),
        _snap(uid="1", arch_index=0, nickname="甲", contribution=12000, con_day=300),
        _snap(uid="3", arch_index=0, nickname="丙", contribution=500, con_day=500),
    ]
    scores = calculate_yesterday(previous, current)
    assert [item.nickname for item in scores] == ["甲", "乙"]
    assert scores[0].yesterday == 3200
    assert scores[1].yesterday == 1100


def test_below_limit_uses_yesterday_score():
    items = [
        YesterdayScore("1", 0, "甲", 2100),
        YesterdayScore("2", 0, "乙", 800),
        YesterdayScore("3", 0, "丙", 1400),
    ]
    assert [item.nickname for item in below_limit(items, 1400)] == ["乙"]


def test_snapshot_from_member_reads_detail():
    member = SimpleNamespace(
        uid="1001",
        index=4,
        nickname="qq名",
        contribution=8888,
        detail=SimpleNamespace(
            playerName="角色名",
            conDay=1234,
            conObj=SimpleNamespace(this_week=5600),
        ),
    )
    item = snapshot_from_member("g", 88, "2026-08-23", member, "now")
    assert item.uid == "1001"
    assert item.arch_index == 4
    assert item.nickname == "角色名"
    assert item.contribution == 8888
    assert item.con_day == 1234
    assert item.this_week == 5600


@pytest.mark.asyncio
async def test_capture_members_dedupes_army_per_group():
    """同一军队被多个群绑定时：只拉取一次成员，但按绑定群各写一份快照。"""
    from types import SimpleNamespace as NS

    from bqyx_bot.handlers.schedule import ScheduleHandlers

    writes: list[tuple[str, int, int]] = []

    class FakeStore:
        async def list_group_armies(self):
            return [("g1", 29802), ("g2", 29802), ("g3", 1241)]

        async def replace_member_snapshots(self, group_id, army_id, snapshot_date, items):
            writes.append((group_id, army_id, len(items)))

    class FakeUser:
        def __init__(self):
            self.calls = 0

        async def get_members(self, army_id):
            self.calls += 1
            return [
                NS(
                    uid="1001",
                    index=0,
                    nickname="qq名",
                    contribution=8888,
                    detail=NS(playerName="角色名", conDay=1234, conObj=NS(this_week=5600)),
                )
            ]

    fake_user = FakeUser()
    handler = ScheduleHandlers()
    handler.store = FakeStore()
    handler.account = NS(get_user=lambda: _afake(fake_user))

    await handler._capture_members()

    # API 只拉 2 次（两个不同军队），29802 只拉一次
    assert fake_user.calls == 2
    # 快照按群写 3 份（g1/g2 各一份 29802，g3 一份 1241）
    assert sorted(writes) == [("g1", 29802, 1), ("g2", 29802, 1), ("g3", 1241, 1)]


async def _afake(user):
    return user


class _FakeDetail:
    def __init__(self, con_day: int) -> None:
        self.conDay = con_day


class _FakeMember:
    def __init__(self, uid: str, con_day: int) -> None:
        self.uid = uid
        self.detail = _FakeDetail(con_day)


def test_apply_yesterday_to_members_overrides_con_day():
    from bqyx_bot.handlers.schedule import apply_yesterday_to_members

    members = [_FakeMember("1", 5), _FakeMember("2", 8)]
    scores = [YesterdayScore("1", 0, "甲", 1400)]
    apply_yesterday_to_members(members, scores)
    assert members[0].detail.conDay == 1400  # 有分数 → 昨日贡献
    assert members[1].detail.conDay == 0  # 新成员无分数 → 默认 0


def test_sort_members_by_yesterday_desc():
    from bqyx_bot.handlers.schedule import sort_members_by_yesterday

    members = [_FakeMember("1", 0), _FakeMember("2", 0), _FakeMember("3", 0)]
    scores = [
        YesterdayScore("2", 0, "乙", 800),
        YesterdayScore("1", 0, "甲", 1400),
        YesterdayScore("3", 0, "丙", 0),
    ]
    sort_members_by_yesterday(members, scores)
    assert [m.uid for m in members] == ["1", "2", "3"]  # 1400 > 800 > 0


