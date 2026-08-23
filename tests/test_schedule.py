from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bqyx_bot.models import MemberSnapshot
from bqyx_bot.schedule import (
    capture_date,
    report_date,
    snapshot_from_member,
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

