from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import MemberSnapshot

SHANGHAI = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class YesterdayScore:
    uid: str
    arch_index: int
    nickname: str
    yesterday: int


def as_shanghai(now: datetime | None = None) -> datetime:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=SHANGHAI)
    return current.astimezone(SHANGHAI)


def capture_date(now: datetime | None = None) -> str:
    local = as_shanghai(now)
    if local.hour < 12:
        local = local - timedelta(days=1)
    return local.date().isoformat()


def report_date(now: datetime | None = None) -> str:
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


def day_baseline(item: MemberSnapshot) -> int:
    return item.contribution - item.con_day


def yesterday_contribution(previous: MemberSnapshot, current: MemberSnapshot) -> int:
    return max(day_baseline(current) - day_baseline(previous), 0)


def calculate_yesterday(
    previous_items: list[MemberSnapshot],
    current_items: list[MemberSnapshot],
) -> list[YesterdayScore]:
    previous_map = {(item.uid, item.arch_index): item for item in previous_items}
    scores: list[YesterdayScore] = []
    for current in current_items:
        previous = previous_map.get((current.uid, current.arch_index))
        if previous is None:
            continue
        scores.append(
            YesterdayScore(
                uid=current.uid,
                arch_index=current.arch_index,
                nickname=current.nickname,
                yesterday=yesterday_contribution(previous, current),
            )
        )
    return rank_scores(scores)


def rank_scores(items: list[YesterdayScore]) -> list[YesterdayScore]:
    return sorted(items, key=lambda item: (-item.yesterday, item.nickname))


def below_limit(items: list[YesterdayScore], limit: int) -> list[YesterdayScore]:
    return [item for item in rank_scores(items) if item.yesterday < limit]


def format_below_text(limit: int, items: list[YesterdayScore]) -> str:
    if not items:
        return f"太棒了！没有人昨日贡献低于 {limit}。"
    lines = [f"以下成员昨日贡献低于 {limit}："]
    for item in items:
        lines.append(f"- {item.nickname} (贡献: {item.yesterday})")
    return "\n".join(lines)
