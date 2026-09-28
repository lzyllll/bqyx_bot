from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from bqyx_api.render import PlayerHtmlRenderer

from ..context import BqyxServices
from ..errors import (
    ArmyNotBoundError,
    BotError,
    GroupOnlyError,
    ParamError,
    UserNotBoundError,
)
from ..hooks import command_rate_limit, error_reply, my_dps_limit
from ..models import ContributionKind
from ..parsing import (
    extract_command_arg,
    parse_format,
    parse_format_and_limit,
    parse_year_month,
)
from ..render import MyContributionRenderer
from ..reply import md_cmd_example, md_cmd_input
from ..schedule import as_shanghai


class QueryHandlers(BqyxServices):
    async def _get_army(self, group_id: str) -> tuple[Any, int]:
        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            raise ArmyNotBoundError()
        user = await self.account.get_user()
        return user, army_id

    @filter.command("我的战力", alias={"战力", "查战力"})
    @error_reply
    @my_dps_limit
    async def check_my_dps(
        self,
        event: AstrMessageEvent,
    ) -> None:
        """查询角色战力面板与加成汇总。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        qq_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            raise UserNotBoundError()

        user = await self.account.get_user()
        account = await user.get_account(bind.uid, bind.arch_index)

        # 获取军队与成员实时数据
        army_id = await self.store.get_group_army(group_id)
        union_info = None
        member_info = None
        member_list = None
        if army_id is not None:
            try:
                union_info = await user.get_union_info(army_id)
                raw_members = await user.get_members(army_id)
                member_list = list(raw_members)
                for m in member_list:
                    if str(m.uid) == str(bind.uid):
                        member_info = m
                        break
            except Exception:
                pass

        service = self.player_bonus
        view, summary = await service.get_role_panel_and_bonus(
            account,
            uid=bind.uid,
            archive_index=bind.arch_index,
            union_info=union_info,
            member_info=member_info,
            member_list=member_list,
        )

        renderer = PlayerHtmlRenderer()
        panel_png = await renderer.panel_image(view)
        bonus_prop_png = await renderer.bonus_image(summary, mode="property")
        bonus_mod_png = await renderer.bonus_image(summary, mode="module")
        arms_png = await renderer.arms_image(view)

        player_name = view.player_name or account.title or bind.uid
        title = f"{player_name} 的战力"
        for res in await self.replies.build_role_dps_report(
            event,
            panel_png,
            bonus_prop_png,
            bonus_mod_png,
            arms_png=arms_png,
            title=title,
        ):
            yield res

    @filter.command("我的贡献", alias={"查贡献","贡献墙", "我的日贡"})
    @error_reply
    @command_rate_limit(name="我的贡献")
    async def check_my_contribution_wall(
        self,
        event: AstrMessageEvent,
        month_arg: str = "",
    ) -> None:
        """查询本月每日日贡贡献日历墙。支持指定月份（如 2026-09 或 上月）。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        qq_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            raise UserNotBoundError()

        raw_text = event.message_str or ""
        now = as_shanghai()
        year, month = parse_year_month(raw_text, default_now=now)

        if not (1 <= month <= 12 and 2000 <= year <= 2100):
            raise ParamError(
                "月份格式无效",
                usage="/我的贡献 或 /我的贡献 2026-09",
                extra="示例：我的贡献 2026-09 或 我的贡献 上月",
            )

        user, army_id = await self._get_army(group_id)

        today = now.date()
        today_str = today.isoformat()
        is_current_month = today.year == year and today.month == month

        # 1. 直接读取 member_daily 真实日贡
        dailies = await self.store.list_member_daily(
            uid=bind.uid,
            year=year,
            month=month,
            army_id=army_id,
        )
        daily_records: dict[str, int | None] = {
            d.date: d.daily_contribution for d in dailies
        }

        player_name = None
        if dailies:
            player_name = dailies[-1].nickname

        # 2. 当月查询：今日通过 API 实时获取，且若昨日 member_daily 缺失则触发一次懒计算入库
        if is_current_month:
            raw_members = await user.get_members(army_id)
            for m in raw_members:
                if str(m.uid) == str(bind.uid):
                    if m.detail:
                        if m.detail.playerName:
                            player_name = str(m.detail.playerName).strip()
                        if m.detail.conDay is not None:
                            daily_records[today_str] = int(m.detail.conDay)
                    break

            # 懒计算昨日真实 daily
            yesterday = today - timedelta(days=1)
            yesterday_str = yesterday.isoformat()
            has_yesterday_daily = any(d.date == yesterday_str for d in dailies)
            if not has_yesterday_daily:
                prev_snapshots = await self.store.list_member_snapshots(
                    army_id, yesterday_str
                )
                if prev_snapshots:
                    from ..schedule import (
                        compute_daily_from_snapshots,
                        snapshot_from_member,
                    )

                    curr_snapshots = [
                        snapshot_from_member(
                            army_id, today_str, m, captured_at=now.isoformat()
                        )
                        for m in raw_members
                    ]
                    computed = compute_daily_from_snapshots(
                        prev_snapshots,
                        curr_snapshots,
                        yesterday_str,
                        computed_at=now.isoformat(),
                    )
                    if computed:
                        await self.store.upsert_member_daily(computed)
                        for cd in computed:
                            if str(cd.uid) == str(bind.uid):
                                daily_records[yesterday_str] = cd.daily_contribution
                                break

        # 3. 角色名兜底
        if not player_name:
            for snap in reversed(
                await self.store.list_member_snapshots_for_month(
                    uid=bind.uid, year=year, month=month, army_id=army_id
                )
            ):
                if snap.nickname:
                    player_name = snap.nickname
                    break

        if not player_name:
            try:
                account = await user.get_account(bind.uid, bind.arch_index)
                player_name = account.title or bind.uid
            except Exception:
                player_name = bind.uid

        renderer = MyContributionRenderer()
        html = renderer.html(
            player_name=player_name,
            year=year,
            month=month,
            daily_records=daily_records,
            captured_at=now.strftime("%Y-%m-%d %H:%M:%S"),
        )
        png = await renderer.to_png(html)
        for res in await self.replies.build_my_contribution_wall(event, png):
            yield res

    @filter.command("查修罗")
    @error_reply
    @command_rate_limit(name="查修罗")
    async def check_demon(
        self,
        event: AstrMessageEvent,
        format_type: str = "图片",
    ):
        """查询自己的修罗地图。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        qq_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            raise UserNotBoundError()

        if format_type not in ("图片", "文本"):
            format_type = parse_format(event.message_str, "图片")

        user = await self.account.get_user()
        account = await user.get_account(bind.uid, bind.arch_index)
        result = self.demon_week.parse_archive(account.data)

        title = f"{account.title} 的修罗地图"
        for res in await self.replies.build_demon(event, result, format_type, title=title):
            yield res

    @filter.command("军队信息")
    @error_reply
    @command_rate_limit(name="军队信息")
    async def check_union_info(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        format_type = parse_format(event.message_str, "图片")
        user, army_id = await self._get_army(group_id)
        union_info = await user.get_union_info(army_id)
        for res in await self.replies.build_union_info(event, union_info, format_type):
            yield res

    @filter.command("查成员")
    @error_reply
    @command_rate_limit(name="查成员")
    async def check_members(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        format_type = parse_format(event.message_str, "图片")
        user, army_id = await self._get_army(group_id)
        members = (await user.get_members(army_id)).sort(
            key=lambda m: m.detail.conDay,
            reverse=True,
        )
        bind = await self.optional_bind(group_id, str(event.get_sender_id()))
        for res in await self.replies.build_members(
            event,
            members,
            format_type,
            file_prefix="members",
            uid=bind.uid if bind else None,
        ):
            yield res

    @filter.command("查争霸")
    @error_reply
    @command_rate_limit(name="查争霸")
    async def check_domain(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        format_type = parse_format(event.message_str, "图片")
        user, army_id = await self._get_army(group_id)
        members = await user.get_members(army_id)
        union_info = await user.get_union_info(army_id)
        bind = await self.optional_bind(group_id, str(event.get_sender_id()))
        for res in await self.replies.build_domain(
            event,
            members,
            union_info,
            format_type,
            uid=bind.uid if bind else None,
        ):
            yield res

    @filter.command("members")
    @error_reply
    @command_rate_limit(name="members")
    async def check_members_by_id(
        self, event: AstrMessageEvent, union_id: str = ""
    ) -> None:
        raw_id = extract_command_arg(union_id, event, ("members",)).strip()
        if not raw_id:
            tag = md_cmd_input("/members", "members")
            ex = md_cmd_example("/members 26490", "members 26490")
            raise ParamError(
                "请输入军队ID",
                usage=f"{tag} `<军队ID>`",
                extra=f"例如：{ex}",
            )
        if not raw_id.isdigit() or int(raw_id) <= 0:
            ex = md_cmd_example("/members 26490", "members 26490")
            raise ParamError(
                "军队ID格式错误：军队 ID 必须是正整数",
                extra=f"例如：{ex}",
            )
        target_id = int(raw_id)
        user = await self.account.get_user()
        members = (await user.get_members(target_id)).sort(
            key=lambda m: m.detail.conDay,
            reverse=True,
        )
        group_id = str(event.get_group_id() or "")
        bind = (
            await self.optional_bind(group_id, str(event.get_sender_id()))
            if group_id
            else None
        )
        for res in await self.replies.build_members(
            event,
            members,
            "图片",
            file_prefix="members",
            uid=bind.uid if bind else None,
        ):
            yield res

    @filter.command("union")
    @error_reply
    @command_rate_limit(name="union")
    async def check_union_by_id(
        self, event: AstrMessageEvent, union_id: str = ""
    ):
        raw_id = extract_command_arg(union_id, event, ("union",)).strip()
        if not raw_id:
            tag = md_cmd_input("/union", "union")
            ex = md_cmd_example("/union 26490", "union 26490")
            raise ParamError(
                "请输入军队ID",
                usage=f"{tag} `<军队ID>`",
                extra=f"例如：{ex}",
            )
        if not raw_id.isdigit() or int(raw_id) <= 0:
            ex = md_cmd_example("/union 26490", "union 26490")
            raise ParamError(
                "军队ID格式错误：军队 ID 必须是正整数",
                extra=f"例如：{ex}",
            )
        target_id = int(raw_id)
        user = await self.account.get_user()
        union = await user.get_union_info(target_id)
        for res in await self.replies.build_union_info(
            event,
            union,
            "图片",
        ):
            yield res

    @filter.command("domain")
    @error_reply
    @command_rate_limit(name="domain")
    async def check_domain_by_id(
        self, event: AstrMessageEvent, union_id: str = ""
    ):
        raw_id = extract_command_arg(union_id, event, ("domain",)).strip()
        if not raw_id:
            tag = md_cmd_input("/domain", "domain")
            ex = md_cmd_example("/domain 26490", "domain 26490")
            raise ParamError(
                "请输入军队ID",
                usage=f"{tag} `<军队ID>`",
                extra=f"例如：{ex}",
            )
        if not raw_id.isdigit() or int(raw_id) <= 0:
            ex = md_cmd_example("/domain 26490", "domain 26490")
            raise ParamError(
                "军队ID格式错误：军队 ID 必须是正整数",
                extra=f"例如：{ex}",
            )
        target_id = int(raw_id)
        user = await self.account.get_user()
        members = await user.get_members(target_id)
        union_info = await user.get_union_info(target_id)
        group_id = str(event.get_group_id() or "")
        bind = (
            await self.optional_bind(group_id, str(event.get_sender_id()))
            if group_id
            else None
        )
        for res in await self.replies.build_domain(
            event,
            members,
            union_info,
            "图片",
            uid=bind.uid if bind else None,
        ):
            yield res

    @filter.command("pk")
    @error_reply
    @command_rate_limit(name="pk")
    async def check_pk_rank_by_id(
        self, event: AstrMessageEvent, union_id: str = ""
    ):
        raw_id = extract_command_arg(union_id, event, ("pk",)).strip()
        if not raw_id:
            tag = md_cmd_input("/pk", "pk")
            ex = md_cmd_example("/pk 26490", "pk 26490")
            raise ParamError(
                "请输入军队ID",
                usage=f"{tag} `<军队ID>`",
                extra=f"例如：{ex}",
            )
        if not raw_id.isdigit() or int(raw_id) <= 0:
            ex = md_cmd_example("/pk 26490", "pk 26490")
            raise ParamError(
                "军队ID格式错误：军队 ID 必须是正整数",
                extra=f"例如：{ex}",
            )
        target_id = int(raw_id)
        user = await self.account.get_user()
        members = await user.get_members(target_id)
        group_id = str(event.get_group_id() or "")
        bind = (
            await self.optional_bind(group_id, str(event.get_sender_id()))
            if group_id
            else None
        )
        for res in await self.replies.build_pk_rank(
            event,
            members,
            "图片",
            uid=bind.uid if bind else None,
        ):
            yield res

    @filter.command("查PK", alias={"查pk", "查pk排行", "查PK排行"})
    @error_reply
    @command_rate_limit(name="查PK")
    async def check_pk_rank(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        format_type = parse_format(event.message_str, "图片")
        user, army_id = await self._get_army(group_id)
        members = await user.get_members(army_id)
        bind = await self.optional_bind(group_id, str(event.get_sender_id()))
        for res in await self.replies.build_pk_rank(
            event,
            members,
            format_type,
            uid=bind.uid if bind else None,
        ):
            yield res

    @filter.command("查日贡")
    @error_reply
    @command_rate_limit(name="查日贡")
    async def check_daily_contribution(self, event: AstrMessageEvent):
        limit, format_type = parse_format_and_limit(
            event.message_str,
            default_limit=ContributionKind.DAILY.default_limit,
            default_format="图片",
        )
        async for res in self._send_contribution(
            event,
            kind=ContributionKind.DAILY,
            limit=limit or ContributionKind.DAILY.default_limit,
            format_type=format_type,
        ):
            yield res

    @filter.command("查周贡")
    @error_reply
    @command_rate_limit(name="查周贡")
    async def check_weekly_contribution(self, event: AstrMessageEvent):
        limit, format_type = parse_format_and_limit(
            event.message_str,
            default_limit=ContributionKind.WEEKLY.default_limit,
            default_format="图片",
        )
        async for res in self._send_contribution(
            event,
            kind=ContributionKind.WEEKLY,
            limit=limit or ContributionKind.WEEKLY.default_limit,
            format_type=format_type,
        ):
            yield res

    @filter.command("查日贡@")
    @error_reply
    @command_rate_limit(name="查日贡@")
    async def check_daily_contribution_with_at(
        self,
        event: AstrMessageEvent,
    ):
        limit, _ = parse_format_and_limit(
            event.message_str,
            default_limit=ContributionKind.DAILY.default_limit,
        )
        async for res in self._send_contribution_at(
            event,
            kind=ContributionKind.DAILY,
            limit=limit or ContributionKind.DAILY.default_limit,
        ):
            yield res

    @filter.command("查周贡@")
    @error_reply
    @command_rate_limit(name="查周贡@")
    async def check_weekly_contribution_with_at(
        self,
        event: AstrMessageEvent,
    ):
        limit, _ = parse_format_and_limit(
            event.message_str,
            default_limit=ContributionKind.WEEKLY.default_limit,
        )
        async for res in self._send_contribution_at(
            event,
            kind=ContributionKind.WEEKLY,
            limit=limit or ContributionKind.WEEKLY.default_limit,
        ):
            yield res

    async def _send_contribution(
        self,
        event: AstrMessageEvent,
        *,
        kind: ContributionKind,
        limit: int,
        format_type: str,
    ):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        user, army_id = await self._get_army(group_id)
        members = (await user.get_members(army_id)).filter(
            lambda m: kind.below_limit(m, limit)
        )
        if not members:
            yield event.plain_result(f"太棒了！没有人{kind.label}低于 {limit}。")
            return

        if format_type == "图片":
            bind = await self.optional_bind(group_id, str(event.get_sender_id()))
            for res in await self.replies.build_members(
                event,
                members,
                "图片",
                title=f"{kind.label}低于 {limit}",
                uid=bind.uid if bind else None,
            ):
                yield res
            return

        lines = [
            f"- {m.detail.playerName} (贡献: {kind.value_of(m)})" for m in members
        ]
        for res in await self.replies.build_members(
            event,
            members,
            format_type,
            title=f"以下成员{kind.label}低于 {limit}：",
            file_prefix=kind.file_prefix,
            text_content=f"以下成员{kind.label}低于 {limit}：\n" + "\n".join(lines),
        ):
            yield res

    async def _send_contribution_at(
        self,
        event: AstrMessageEvent,
        *,
        kind: ContributionKind,
        limit: int,
    ):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        user, army_id = await self._get_army(group_id)
        members = (await user.get_members(army_id)).filter(
            lambda m: kind.below_limit(m, limit)
        )
        if not members:
            yield event.plain_result(f"太棒了！没有人{kind.label}低于 {limit}。")
            return

        binds = await self.store.list_user_binds(group_id)
        uid_to_qq = {item.uid: item.qq_id for item in binds}
        exclude_list = set(await self.store.list_exclude(group_id))

        res = MessageEventResult().message(f"以下成员{kind.label}低于 {limit}：\n")
        for member in members:
            qq_id = uid_to_qq.get(str(member.uid))
            res.message(f"- {member.detail.playerName} (贡献: {kind.value_of(member)}) ")
            if qq_id and qq_id not in exclude_list:
                res.at(qq_id)
            res.message("\n")

        yield res
