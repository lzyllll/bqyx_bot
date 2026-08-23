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
    group_id: str
    army_id: int
    snapshot_date: str
    uid: str
    arch_index: int
    nickname: str
    contribution: int
    con_day: int
    this_week: int
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
