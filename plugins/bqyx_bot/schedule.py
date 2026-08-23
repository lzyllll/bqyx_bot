from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import MemberSnapshot

SHANGHAI = timezone(timedelta(hours=8))


def as_shanghai(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def capture_date(now: datetime | None = None) -> str:
    """采集归属日期：上海时区中午 12 点前算昨天，之后算当天。"""
    local = as_shanghai(now)
    if local.hour < 12:
        local = local - timedelta(days=1)
    return local.date().isoformat()


def report_date(now: datetime | None = None) -> str:
    """查询"昨日"数据用的日期：上海时区今天减一天。"""
    local = as_shanghai(now) - timedelta(days=1)
    return local.date().isoformat()


def snapshot_from_member(
    group_id: str,
    army_id: int,
    snapshot_date: str,
    member,
    captured_at: str,
) -> MemberSnapshot:
    detail = getattr(member, "detail", None)
    nickname = str(getattr(detail, "playerName", "") or "").strip()
    if not nickname:
        nickname = str(getattr(member, "nickname", "") or member.uid).strip()
    con_obj = getattr(detail, "conObj", None)
    return MemberSnapshot(
        group_id=str(group_id),
        army_id=int(army_id),
        snapshot_date=str(snapshot_date),
        uid=str(member.uid),
        arch_index=int(getattr(member, "index", 0) or 0),
        nickname=nickname or str(member.uid),
        contribution=int(getattr(member, "contribution", 0) or 0),
        con_day=int(getattr(detail, "conDay", 0) or 0),
        this_week=int(getattr(con_obj, "this_week", 0) or 0),
        captured_at=captured_at,
    )
