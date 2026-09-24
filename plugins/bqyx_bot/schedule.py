from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import MemberDaily, MemberSnapshot

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
    """采集归属日期：严格以采集时刻所在的上海自然日作为快照日期。"""
    return as_shanghai(now).date().isoformat()


def report_date(now: datetime | None = None) -> str:
    """查询"昨日"数据用的日期：上海时区今天减一天。"""
    local = as_shanghai(now) - timedelta(days=1)
    return local.date().isoformat()


def last_sunday(now: datetime | None = None):
    """本周开始前的那个周日（上海时区日期）。周一的前一天。"""
    today = as_shanghai(now).date()
    return today - timedelta(days=today.weekday() + 1)


def last_week_range(now: datetime | None = None) -> tuple[str, str]:
    """返回 (上周开始前周日, 上周末周日)。"""
    end = last_sunday(now)
    start = end - timedelta(days=7)
    return start.isoformat(), end.isoformat()


def this_week_label(now: datetime | None = None) -> str:
    start = last_sunday(now) + timedelta(days=1)
    today = as_shanghai(now).date()
    return f"{start.isoformat()} ~ {today.isoformat()}"


def last_week_label(now: datetime | None = None) -> str:
    end = last_sunday(now)
    start = end - timedelta(days=6)
    return f"{start.isoformat()} ~ {end.isoformat()}"


def snapshot_from_member(
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
    """计算快照所属自然日的「0点总贡献」（0点起步基线）。"""
    return item.contribution - item.con_day


def yesterday_contribution(previous: MemberSnapshot, current: MemberSnapshot) -> int:
    """通过相邻两次快照的0点总贡献之差，计算出昨天的真实日贡。"""
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


def compute_daily_from_snapshots(
    previous_items: list[MemberSnapshot],
    current_items: list[MemberSnapshot],
    target_date: str,
    computed_at: str | None = None,
) -> list[MemberDaily]:
    """通过相邻两天快照计算目标日期的真实完整日贡。

    计算公式：
        0点总贡献(D)   = snapshot[D].contribution - snapshot[D].con_day
        0点总贡献(D+1) = snapshot[D+1].contribution - snapshot[D+1].con_day
        真实日贡(D)    = 0点总贡献(D+1) - 0点总贡献(D)
    若无前一日快照，则回退为目标日快照中的 con_day。
    """
    previous_map = {item.uid: item for item in previous_items}
    records: list[MemberDaily] = []
    now_str = computed_at or datetime.now(timezone.utc).isoformat()

    for current in current_items:
        prev = previous_map.get(current.uid)
        if prev is not None:
            curr_start = current.contribution - current.con_day
            prev_start = prev.contribution - prev.con_day
            daily_val = max(curr_start - prev_start, 0)
        else:
            daily_val = max(current.con_day, 0)

        records.append(
            MemberDaily(
                army_id=current.army_id,
                date=target_date,
                uid=current.uid,
                nickname=current.nickname,
                daily_contribution=daily_val,
                end_of_day_total=current.contribution,
                computed_at=now_str,
            )
        )
    return records


def rank_scores(items: list[YesterdayScore]) -> list[YesterdayScore]:
    return sorted(items, key=lambda item: (-item.yesterday, item.nickname))


def below_limit(items: list[YesterdayScore], limit: int) -> list[YesterdayScore]:
    return [item for item in rank_scores(items) if item.yesterday < limit]
