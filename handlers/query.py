from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from bqyx_api.render import PlayerHtmlRenderer

from ..context import BqyxServices
from ..hooks import command_rate_limit, error_reply, my_dps_limit
from ..models import ContributionKind
from ..parsing import (
    extract_command_arg,
    parse_format,
    parse_format_and_limit,
    parse_year_month,
)
from ..render import MyContributionRenderer
from ..schedule import as_shanghai


class QueryHandlers(BqyxServices):
    async def _get_army(self, group_id: str) -> tuple[Any, int] | None:
        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            return None
        user = await self.account.get_user()
        return user, army_id

    @error_reply
    @my_dps_limit
    @filter.command("我的战力", alias={"战力", "查战力"})
    async def check_my_dps(
        self,
        event: AstrMessageEvent,
    ) -> None:
        """查询角色战力面板与加成汇总。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        qq_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            yield self.replies.markdown_tip(
                event,
                "你尚未在本群绑定游戏角色",
                "/绑定游戏名 <角色名> 或 /绑定uid <UID>",
                "例如：/绑定游戏名 张三",
            )
            return

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

    @error_reply
    @command_rate_limit(name="我的贡献")
    @filter.command("我的贡献", alias={"贡献墙", "我的日贡"})
    async def check_my_contribution_wall(
        self,
        event: AstrMessageEvent,
        month_arg: str = "",
    ) -> None:
        """查询本月每日日贡贡献日历墙。支持指定月份（如 2026-09 或 上月）。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        qq_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            yield self.replies.markdown_tip(
                event,
                "你尚未在本群绑定游戏角色",
                "/绑定游戏名 <角色名> 或 /绑定uid <UID>",
                "例如：/绑定游戏名 张三",
            )
            return

        raw_text = event.message_str or ""
        now = as_shanghai()
        year, month = parse_year_month(raw_text, default_now=now)

        if not (1 <= month <= 12 and 2000 <= year <= 2100):
            yield self.replies.markdown_tip(
                event,
                "月份格式无效",
                "/我的贡献 或 /我的贡献 2026-09",
                "示例：我的贡献 2026-09 或 我的贡献 上月",
            )
            return

        army_info = await self._get_army(group_id)
        if not army_info:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user, army_id = army_info

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

    @error_reply
    @command_rate_limit(name="查修罗")
    @filter.command("查修罗")
    async def check_demon(
        self,
        event: AstrMessageEvent,
        format_type: str = "图片",
    ):
        """查询自己的修罗地图。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        qq_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            yield self.replies.markdown_tip(
                event,
                "你尚未在本群绑定游戏角色",
                "/绑定游戏名 <角色名> 或 /绑定uid <UID>",
                "例如：/绑定游戏名 张三",
            )
            return

        if format_type not in ("图片", "文本"):
            format_type = parse_format(event.message_str, "图片")

        user = await self.account.get_user()
        account = await user.get_account(bind.uid, bind.arch_index)
        result = self.demon_week.parse_archive(account.data)

        title = f"{account.title} 的修罗地图"
        for res in await self.replies.build_demon(event, result, format_type, title=title):
            yield res

    @error_reply
    @command_rate_limit(name="军队信息")
    @filter.command("军队信息")
    async def check_union_info(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        format_type = parse_format(event.message_str, "图片")
        army_info = await self._get_army(group_id)
        if not army_info:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user, army_id = army_info
        union_info = await user.get_union_info(army_id)
        for res in await self.replies.build_union_info(event, union_info, format_type):
            yield res

    @error_reply
    @command_rate_limit(name="查成员")
    @filter.command("查成员")
    async def check_members(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        format_type = parse_format(event.message_str, "图片")
        army_info = await self._get_army(group_id)
        if not army_info:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user, army_id = army_info
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

    @error_reply
    @command_rate_limit(name="查争霸")
    @filter.command("查争霸")
    async def check_domain(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        format_type = parse_format(event.message_str, "图片")
        army_info = await self._get_army(group_id)
        if not army_info:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user, army_id = army_info
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

    @error_reply
    @command_rate_limit(name="members")
    @filter.command("members")
    async def check_members_by_id(
        self, event: AstrMessageEvent, union_id: str = ""
    ) -> None:
        raw_id = extract_command_arg(union_id, event, ("members")).strip()
        if not raw_id:
            yield self.replies.markdown_tip(
                event,
                "请输入军队ID",
                "/members <军队ID>",
                "例如：/members 26490",
            )
            return
        if not raw_id.isdigit() or int(raw_id) <= 0:
            yield self.replies.markdown_warn(
                event,
                "军队ID格式错误：军队 ID 必须是正整数，例如 /members 26490",
            )
            return
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

    @error_reply
    @command_rate_limit(name="union")
    @filter.command("union")
    async def check_union_by_id(
        self, event: AstrMessageEvent, union_id: str = ""
    ):
        raw_id = extract_command_arg(union_id, event, ("union")).strip()
        if not raw_id:
            yield self.replies.markdown_tip(
                event,
                "请输入军队ID",
                "/union <军队ID>",
                "例如：/union 26490",
            )
            return
        if not raw_id.isdigit() or int(raw_id) <= 0:
            yield self.replies.markdown_warn(
                event,
                "军队ID格式错误：军队 ID 必须是正整数，例如 /union 26490",
            )
            return
        target_id = int(raw_id)
        user = await self.account.get_user()
        union = await user.get_union_info(target_id)
        for res in await self.replies.build_union_info(
            event,
            union,
            "图片",
        ):
            yield res

    @error_reply
    @command_rate_limit(name="domain")
    @filter.command("domain")
    async def check_domain_by_id(
        self, event: AstrMessageEvent, union_id: str = ""
    ):
        raw_id = extract_command_arg(union_id, event, ("domain")).strip()
        if not raw_id:
            yield self.replies.markdown_tip(
                event,
                "请输入军队ID",
                "/domain <军队ID>",
                "例如：/domain 26490",
            )
            return
        if not raw_id.isdigit() or int(raw_id) <= 0:
            yield self.replies.markdown_warn(
                event,
                "军队ID格式错误：军队 ID 必须是正整数，例如 /domain 26490",
            )
            return
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

    @error_reply
    @command_rate_limit(name="pk")
    @filter.command("pk")
    async def check_pk_rank_by_id(
        self, event: AstrMessageEvent, union_id: str = ""
    ):
        raw_id = extract_command_arg(union_id, event, ("pk")).strip()
        if not raw_id:
            yield self.replies.markdown_tip(
                event,
                "请输入军队ID",
                "/pk <军队ID>",
                "例如：/pk 26490",
            )
            return
        if not raw_id.isdigit() or int(raw_id) <= 0:
            yield self.replies.markdown_warn(
                event,
                "军队ID格式错误：军队 ID 必须是正整数，例如 /pk 26490",
            )
            return
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

    @error_reply
    @command_rate_limit(name="查PK")
    @filter.command("查PK", alias={"查pk", "查pk排行", "查PK排行"})
    async def check_pk_rank(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        format_type = parse_format(event.message_str, "图片")
        army_info = await self._get_army(group_id)
        if not army_info:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user, army_id = army_info
        members = await user.get_members(army_id)
        bind = await self.optional_bind(group_id, str(event.get_sender_id()))
        for res in await self.replies.build_pk_rank(
            event,
            members,
            format_type,
            uid=bind.uid if bind else None,
        ):
            yield res

    @error_reply
    @command_rate_limit(name="查日贡")
    @filter.command("查日贡")
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

    @error_reply
    @command_rate_limit(name="查周贡")
    @filter.command("查周贡")
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

    @error_reply
    @command_rate_limit(name="查日贡@")
    @filter.command("查日贡@")
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

    @error_reply
    @command_rate_limit(name="查周贡@")
    @filter.command("查周贡@")
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
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        army_info = await self._get_army(group_id)
        if not army_info:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user, army_id = army_info
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
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        army_info = await self._get_army(group_id)
        if not army_info:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user, army_id = army_info
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
