from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


@dataclass(frozen=True)
class UserBind:
    group_id: str
    qq_id: str
    uid: str
    arch_index: int


@dataclass(frozen=True)
class QQMember:
    qq_id: str
    nickname: str


@dataclass(frozen=True)
class GameMember:
    uid: str
    arch_index: int
    nickname: str


@dataclass(frozen=True)
class MemberSnapshot:
    """某军队在某一天（23:30 采集）的成员贡献指标快照。

    快照按「军队」存储（不按 QQ 群）：同一军队被多个群绑定时共享一份，
    群改绑军队后无需等待重新采集；群维度由 group_army 绑定表负责。

    字段语义（均来自 4399 游戏接口）：
    - contribution: 游戏总贡献（服务端累计值）
    - con_day: 今日贡献（游戏内每天 0 点刷新）
    - this_week: 本周贡献（按周代码从 conObj 解析）
    """

    army_id: int
    snapshot_date: str
    uid: str
    arch_index: int
    nickname: str
    contribution: int
    con_day: int
    this_week: int
    captured_at: str


@dataclass(frozen=True)
class MemberDaily:
    """某成员某天的真实完整日贡（由连续两天快照 baseline 差值计算得出）。"""

    army_id: int
    date: str
    uid: str
    nickname: str
    daily_contribution: int
    end_of_day_total: int
    computed_at: str


@dataclass(frozen=True)
class UnionSnapshot:
    """某一天 23:59 采集的军队排行快照（前 1000 名）。"""

    snapshot_date: str
    rank: int
    union_id: int
    name: str
    level: int
    members_num: int
    contribution: int
    today_contribution: int | None
    captured_at: str


class ContributionKind(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"

    @property
    def label(self) -> str:
        if self is ContributionKind.DAILY:
            return "今日贡献"
        return "本周贡献"

    @property
    def file_prefix(self) -> str:
        if self is ContributionKind.DAILY:
            return "daily_contribution"
        return "weekly_contribution"

    @property
    def default_limit(self) -> int:
        if self is ContributionKind.DAILY:
            return 1400
        return 9800

    def below_limit(self, member: Any, limit: int) -> bool:
        return self.value_of(member) < limit

    def value_of(self, member: Any) -> int:
        if self is ContributionKind.DAILY:
            return int(member.detail.conDay)
        return int(member.detail.conObj.this_week)
