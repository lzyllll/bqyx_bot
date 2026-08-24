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

    注意：这里存的是「当日全量指标快照」，不是「昨日贡献」。
    「昨日贡献」是派生值，由前后两天快照对比计算得出
    （`yesterday_contribution = (contribution - con_day) 的差值`），并不落库。

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
    contribution: int  # 总贡献（累计值）
    con_day: int  # 今日贡献（0 点刷新）
    this_week: int  # 本周贡献
    captured_at: str


@dataclass(frozen=True)
class UnionSnapshot:
    """某一天 23:59 采集的军队排行快照（前 1000 名）。

    接口（get_union_list）只提供总贡献 contribution，没有「今日贡献」，
    所以只能在接近零点采集，用相邻两天总贡献的差值计算日贡：
    - contribution: 当天采集到的总贡献（服务端累计值）
    - today_contribution: 当日新增贡献 = 本次 contribution - 昨日快照 contribution
    「昨日日贡」即昨日快照的 today_contribution，直接读库即可。
    快照默认保留 15 天，本周/上周周贡由周日快照的总贡献差在查询时计算，不落库。
    """

    snapshot_date: str
    rank: int
    union_id: int
    name: str
    level: int
    members_num: int
    contribution: int  # 总贡献（累计值）
    today_contribution: int | None  # 当日新增贡献（相邻两天快照对比）；无基线（首次采集）为 None
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
