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
    """某军队成员在某一天（23:30 采集）的贡献指标快照。

    注意：这里存的是「当日全量指标快照」，不是「昨日贡献」。
    「昨日贡献」是派生值，由前后两天快照对比计算得出
    （`yesterday_contribution = (contribution - con_day) 的差值`），并不落库。

    字段语义（均来自 4399 游戏接口）：
    - contribution: 游戏总贡献（服务端累计值）
    - con_day: 今日贡献（游戏内每天 0 点刷新）
    - this_week: 本周贡献（按周代码从 conObj 解析）
    """

    group_id: str
    army_id: int
    snapshot_date: str
    uid: str
    arch_index: int
    nickname: str
    contribution: int  # 总贡献（累计值）
    con_day: int  # 今日贡献（0 点刷新）
    this_week: int  # 本周贡献
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
