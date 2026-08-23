from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types import MessageArray

from ..context import BqyxServices
from ..errors import BotError
from ..hooks import error_reply, query_limit
from ..models import ContributionKind, MemberSnapshot
from ..parsing import parse_format_and_limit
from ..schedule import (
    YesterdayScore,
    below_limit,
    calculate_yesterday,
    capture_date,
    format_below_text,
    report_date,
    snapshot_from_member,
)

LOG = logging.getLogger("bqyx_bot.schedule")


class ScheduleHandlers(BqyxServices):
    async def capture_members(self) -> None:
        async with self._lock():
            await self._capture_members()

    async def report_yesterday(self) -> None:
        async with self._lock():
            await self._report_yesterday()

    @error_reply
    @query_limit
    @registrar.on_group_command("昨日贡献")
    async def check_yesterday_contribution(self, event: GroupMessageEvent) -> None:
        resolved = self._yesterday_limit(event)
        missing = await self._yesterday_below(str(event.group_id), resolved)
        text = format_below_text(resolved, missing)
        if len(text) > 400:
            await self.replies.send_forward_text(event, text)
            return
        await event.reply(text)

    @error_reply
    @query_limit
    @registrar.on_group_command("昨日贡献@")
    async def check_yesterday_contribution_with_at(self, event: GroupMessageEvent) -> None:
        resolved = self._yesterday_limit(event)
        group_id = str(event.group_id)
        missing = await self._yesterday_below(group_id, resolved)
        if not missing:
            await event.reply(format_below_text(resolved, missing))
            return
        await event.reply(rtf=await self._yesterday_at_chain(group_id, missing, resolved))

    def _yesterday_limit(self, event: GroupMessageEvent) -> int:
        limit, _ = parse_format_and_limit(
            event.message.text,
            default_limit=ContributionKind.DAILY.default_limit,
            default_format="文本",
        )
        return limit if limit is not None else ContributionKind.DAILY.default_limit

    async def _yesterday_below(self, group_id: str, limit: int) -> list[YesterdayScore]:
        user, army_id = await self.require_army(group_id)
        _day, scores = await self._yesterday_scores(
            group_id,
            army_id,
            user=user,
            army_cache={},
        )
        return below_limit(scores, limit)

    def _lock(self) -> asyncio.Lock:
        lock = getattr(self, "_nightly_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._nightly_lock = lock
        return lock

    async def _capture_members(self) -> None:
        groups = await self.store.list_group_armies()
        if not groups:
            LOG.info("没有已绑定军队的群，跳过成员采集")
            return

        user = await self.account.get_user()
        snapshot_day = capture_date()
        captured_at = datetime.now(timezone.utc).isoformat()
        army_cache: dict[int, list] = {}
        ok = 0
        for group_id, army_id in groups:
            try:
                items = await self._live_snapshots(
                    user,
                    army_cache,
                    group_id,
                    army_id,
                    snapshot_day,
                    captured_at,
                )
                await self.store.replace_member_snapshots(
                    group_id,
                    army_id,
                    snapshot_day,
                    items,
                )
                ok += 1
                LOG.info(
                    "已采集群 %s 军队 %s 成员 %s 人（%s）",
                    group_id,
                    army_id,
                    len(items),
                    snapshot_day,
                )
            except Exception:
                LOG.exception("采集群 %s 军队 %s 失败", group_id, army_id)
        LOG.info("成员采集完成：%s/%s 个群", ok, len(groups))

    async def _report_yesterday(self) -> None:
        groups = await self.store.list_group_armies()
        if not groups:
            LOG.info("没有已绑定军队的群，跳过昨日贡献")
            return

        captured_at = datetime.now(timezone.utc).isoformat()
        limit = ContributionKind.DAILY.default_limit
        user = await self.account.get_user()
        army_cache: dict[int, list] = {}
        ok = 0
        for group_id, army_id in groups:
            try:
                previous_day, scores = await self._yesterday_scores(
                    group_id,
                    army_id,
                    user=user,
                    army_cache=army_cache,
                    captured_at=captured_at,
                )
                ok += 1
                LOG.info(
                    "群 %s 昨日贡献已计算：%s 人（%s，阈值 %s）",
                    group_id,
                    len(scores),
                    previous_day,
                    limit,
                )
            except BotError as exc:
                LOG.warning("群 %s 昨日贡献跳过：%s", group_id, exc)
            except Exception:
                LOG.exception("群 %s 昨日贡献计算失败", group_id)
        LOG.info("昨日贡献计算完成：%s/%s 个群", ok, len(groups))

    async def _yesterday_scores(
        self,
        group_id: str,
        army_id: int,
        *,
        user,
        army_cache: dict[int, list],
        captured_at: str | None = None,
    ) -> tuple[str, list[YesterdayScore]]:
        previous_day = report_date()
        previous = await self.store.list_member_snapshots(group_id, previous_day)
        if not previous:
            raise BotError(f"没有 {previous_day} 的 成员快照，请等晚上采集完成后再试。")
        current = await self._live_snapshots(
            user,
            army_cache,
            group_id,
            army_id,
            previous_day,
            captured_at or datetime.now(timezone.utc).isoformat(),
        )
        return previous_day, calculate_yesterday(previous, current)

    async def _live_snapshots(
        self,
        user,
        army_cache: dict[int, list],
        group_id: str,
        army_id: int,
        snapshot_day: str,
        captured_at: str,
    ) -> list[MemberSnapshot]:
        if army_id not in army_cache:
            army_cache[army_id] = list(await user.get_members(army_id))
        return [
            snapshot_from_member(
                group_id,
                army_id,
                snapshot_day,
                member,
                captured_at,
            )
            for member in army_cache[army_id]
        ]

    async def _yesterday_at_chain(
        self,
        group_id: str,
        missing: list[YesterdayScore],
        limit: int,
    ) -> MessageArray:
        binds = await self.store.list_user_binds(group_id)
        uid_to_qq = {item.uid: item.qq_id for item in binds}
        exclude_list = set(await self.store.list_exclude(group_id))
        group_qq_ids: set[str] = set()
        try:
            group_members = await self.api.qq.query.get_group_member_list(int(group_id))
            group_qq_ids = {str(member.user_id) for member in group_members}
        except Exception:
            LOG.exception("获取群 %s 成员列表失败，昨日贡献将不 @", group_id)

        chain = MessageArray()
        chain.add_text(f"以下成员昨日贡献低于 {limit}：\n")
        for member in missing:
            qq_id = uid_to_qq.get(member.uid)
            chain.add_text(f"- {member.nickname} (贡献: {member.yesterday}) ")
            if qq_id and qq_id in group_qq_ids:
                if qq_id in exclude_list:
                    chain.add_text(f"(免@: {qq_id})")
                else:
                    chain.add_at(qq_id)
            elif qq_id:
                chain.add_text("(已离群)")
            else:
                chain.add_text("(未绑定)")
            chain.add_text("\n")
        return chain
