import re
from datetime import timedelta

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types import At, MessageArray

from ..context import BqyxServices
from ..errors import BotError, UserNotBoundError
from ..hooks import command_rate_limit, error_reply, my_dps_limit
from ..models import ContributionKind
from ..parsing import (
    extract_at,
    parse_format,
    parse_format_and_limit,
    parse_year_month,
)
from ..render import MyContributionRenderer
from ..schedule import as_shanghai
from bqyx_api.archive.player.render import (
    render_role_arms_image_async,
    render_role_bonus_image_async,
    render_role_panel_image_async,
)

class QueryHandlers(BqyxServices):
    @error_reply
    @my_dps_limit
    @registrar.on_group_command("我的战力", "战力", "查战力")
    async def check_my_dps(
        self,
        event: GroupMessageEvent,
        target: At | None = None,
    ) -> None:
        """查询角色战力面板与加成汇总（合并转发嵌套卡片）。"""
        group_id = str(event.group_id)
        target_at = extract_at(event, target)
        is_other = target_at is not None
        qq_id = str(target_at.user_id if target_at else event.user_id)

        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            if is_other:
                raise BotError("被 @ 的用户尚未在本群绑定游戏账号。")
            raise UserNotBoundError()

        user = await self.account.get_user()
        account = await user.get_account(bind.uid, bind.arch_index)

        # 获取军队与成员实时数据（若群已绑定军队且包含该成员，可计算军队军衔与争霸加成）
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
        view, summary = await service.get_role_panel_and_bonus_async(
            account,
            uid=bind.uid,
            archive_index=bind.arch_index,
            union_info=union_info,
            member_info=member_info,
            member_list=member_list,
        )

        panel_png = await render_role_panel_image_async(view)
        bonus_prop_png = await render_role_bonus_image_async(summary, mode="property")
        bonus_mod_png = await render_role_bonus_image_async(summary, mode="module")
        arms_png = await render_role_arms_image_async(view)

        player_name = view.player_name or account.title or bind.uid
        title = f"{player_name} 的战力"
        await self.replies.send_role_dps_report(
            event,
            panel_png,
            bonus_prop_png,
            bonus_mod_png,
            arms_png=arms_png,
            title=title,
        )

    @error_reply
    @command_rate_limit(name="我的贡献")
    @registrar.on_group_command("我的贡献", "贡献墙", "我的日贡")
    async def check_my_contribution_wall(
        self,
        event: GroupMessageEvent,
        target: At | None = None,
    ) -> None:
        """查询本月每日日贡贡献日历墙。支持 @用户 以及指定月份（如 2026-09 或 上月）。"""
        group_id = str(event.group_id)
        target_at = extract_at(event, target)
        is_other = target_at is not None
        qq_id = str(target_at.user_id if target_at else event.user_id)

        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            if is_other:
                raise BotError("被 @ 的用户尚未在本群绑定游戏账号。")
            raise UserNotBoundError()

        # 解析查询月份（默认当月；支持 2026-09、2026/09、202609、上月、9月 等）
        raw_text = event.message.text if hasattr(event, "message") and hasattr(event.message, "text") else ""
        now = as_shanghai()
        year, month = parse_year_month(raw_text, default_now=now)

        if not (1 <= month <= 12 and 2000 <= year <= 2100):
            raise BotError("月份格式无效，示例：我的贡献 或 我的贡献 2026-09")

        user, army_id = await self.require_army(group_id)

        today = now.date()
        today_str = today.isoformat()
        is_current_month = (today.year == year and today.month == month)

        # 1. 直接读取 member_daily 真实日贡（两表分离结构，不再混入旧快照）
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
                        # 今日是通过 API 实时获取
                        if m.detail.conDay is not None:
                            daily_records[today_str] = int(m.detail.conDay)
                    break

            # 懒计算昨日真实 daily：如果昨天尚未写入 member_daily，则触发一次计算入库
            yesterday = today - timedelta(days=1)
            yesterday_str = yesterday.isoformat()
            has_yesterday_daily = any(d.date == yesterday_str for d in dailies)
            if not has_yesterday_daily:
                prev_snapshots = await self.store.list_member_snapshots(army_id, yesterday_str)
                if prev_snapshots:
                    from ..schedule import compute_daily_from_snapshots, snapshot_from_member

                    curr_snapshots = [
                        snapshot_from_member(army_id, today_str, m, captured_at=now.isoformat())
                        for m in raw_members
                    ]
                    computed = compute_daily_from_snapshots(
                        prev_snapshots, curr_snapshots, yesterday_str, computed_at=now.isoformat()
                    )
                    if computed:
                        await self.store.upsert_member_daily(computed)
                        for cd in computed:
                            if str(cd.uid) == str(bind.uid):
                                daily_records[yesterday_str] = cd.daily_contribution
                                break

        # 3. 角色名兜底
        if not player_name:
            for snap in reversed(await self.store.list_member_snapshots_for_month(uid=bind.uid, year=year, month=month, army_id=army_id)):
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
        await self.replies.send_my_contribution_wall(event, png)

    @error_reply
    @command_rate_limit(name="查修罗")
    @registrar.on_group_command("查修罗")
    async def check_demon(
        self,
        event: GroupMessageEvent,
        target: At | None = None,
        format_type: str = "图片",
    ) -> None:
        """查询自己的修罗地图，或通过 @用户 查询其已绑定的存档。"""
        group_id = str(event.group_id)
        if target in ('图片','文本'):
            format_type = target
            target = None
        qq_id = str(target.user_id if target else event.user_id)
        bind = await self.store.get_user_bind(group_id, qq_id)
        if bind is None:
            if target is None:
                raise UserNotBoundError()
            raise BotError("被 @ 的用户尚未在本群绑定游戏账号。")
        user = await self.account.get_user()
        account = await user.get_account(bind.uid, bind.arch_index)
        result = self.demon_week.parse_archive(account.data)

        title =  f"{account.title} 的修罗地图"
        await self.replies.send_demon(event, result, format_type, title=title)

    @error_reply
    @command_rate_limit(name="军队信息")
    @registrar.on_group_command("军队信息")
    async def check_union_info(self, event: GroupMessageEvent) -> None:
        format_type = parse_format(event.message.text, "图片")
        user, army_id = await self.require_army(str(event.group_id))
        union_info = await user.get_union_info(army_id)
        await self.replies.send_union_info(event, union_info, format_type)

    @error_reply
    @command_rate_limit(name="查成员")
    @registrar.on_group_command("查成员")
    async def check_members(self, event: GroupMessageEvent) -> None:
        format_type = parse_format(event.message.text, "图片")
        user, army_id = await self.require_army(str(event.group_id))
        members = (await user.get_members(army_id)).sort(
            key=lambda m: m.detail.conDay,
            reverse=True,
        )
        bind = await self.optional_bind(str(event.group_id), str(event.user_id))
        await self.replies.send_members(
            event,
            members,
            format_type,
            file_prefix="members",
            uid=bind.uid if bind else None,
        )

    @error_reply
    @command_rate_limit(name="查争霸")
    @registrar.on_group_command("查争霸")
    async def check_domain(self, event: GroupMessageEvent) -> None:
        format_type = parse_format(event.message.text, "图片")
        user, army_id = await self.require_army(str(event.group_id))
        members = await user.get_members(army_id)
        union_info = await user.get_union_info(army_id)
        bind = await self.optional_bind(str(event.group_id), str(event.user_id))
        await self.replies.send_domain(
            event,
            members,
            union_info,
            format_type,
            uid=bind.uid if bind else None,
        )

    @error_reply
    @command_rate_limit(name="/members")
    @registrar.on_group_command("/members", ignore_case=True)
    async def check_members_by_id(self, event: GroupMessageEvent, union_id: int) -> None:
        if union_id <= 0:
            raise BotError("军队 ID 必须是正整数")
        user = await self.account.get_user()
        members = (await user.get_members(union_id)).sort(
            key=lambda m: m.detail.conDay,
            reverse=True,
        )
        bind = await self.optional_bind(str(event.group_id), str(event.user_id))
        await self.replies.send_members(
            event,
            members,
            "图片",
            file_prefix="members",
            uid=bind.uid if bind else None,
        )
    @error_reply
    @command_rate_limit(name="/union")
    @registrar.on_group_command("/union", ignore_case=True)
    async def check_members_by_id(self, event: GroupMessageEvent, union_id: int) -> None:
        if union_id <= 0:
            raise BotError("军队 ID 必须是正整数")
        user = await self.account.get_user()
        union = await user.get_union_info(union_id)
        bind = await self.optional_bind(str(event.group_id), str(event.user_id))
        await self.replies.send_union_info(
            event,
            union,
            "图片",
        )

    @error_reply
    @command_rate_limit(name="/domain")
    @registrar.on_group_command("/domain", ignore_case=True)
    async def check_domain_by_id(self, event: GroupMessageEvent, union_id: int) -> None:
        if union_id <= 0:
            raise BotError("军队 ID 必须是正整数")
        user = await self.account.get_user()
        members = await user.get_members(union_id)
        union_info = await user.get_union_info(union_id)
        bind = await self.optional_bind(str(event.group_id), str(event.user_id))
        await self.replies.send_domain(
            event,
            members,
            union_info,
            "图片",
            uid=bind.uid if bind else None,
        )

    @error_reply
    @command_rate_limit(name="/pk")
    @registrar.on_group_command("/pk", ignore_case=True)
    async def check_pk_rank_by_id(self, event: GroupMessageEvent, union_id: int) -> None:
        if union_id <= 0:
            raise BotError("军队 ID 必须是正整数")
        user = await self.account.get_user()
        members = await user.get_members(union_id)
        bind = await self.optional_bind(str(event.group_id), str(event.user_id))
        await self.replies.send_pk_rank(
            event,
            members,
            "图片",
            uid=bind.uid if bind else None,
        )

    @error_reply
    @command_rate_limit(name="查PK")
    @registrar.on_group_command("查PK", "查pk", "查pk排行", "查PK排行")
    async def check_pk_rank(self, event: GroupMessageEvent) -> None:
        format_type = parse_format(event.message.text, "图片")
        user, army_id = await self.require_army(str(event.group_id))
        members = await user.get_members(army_id)
        bind = await self.optional_bind(str(event.group_id), str(event.user_id))
        await self.replies.send_pk_rank(
            event,
            members,
            format_type,
            uid=bind.uid if bind else None,
        )

    @error_reply
    @command_rate_limit(name="查日贡")
    @registrar.on_group_command("查日贡")
    async def check_daily_contribution(self, event: GroupMessageEvent) -> None:
        limit, format_type = parse_format_and_limit(
            event.message.text,
            default_limit=ContributionKind.DAILY.default_limit,
            default_format="文本",
        )
        await self._send_contribution(
            event,
            kind=ContributionKind.DAILY,
            limit=limit or ContributionKind.DAILY.default_limit,
            format_type=format_type,
        )

    @error_reply
    @command_rate_limit(name="查周贡")
    @registrar.on_group_command("查周贡")
    async def check_weekly_contribution(self, event: GroupMessageEvent) -> None:
        limit, format_type = parse_format_and_limit(
            event.message.text,
            default_limit=ContributionKind.WEEKLY.default_limit,
            default_format="文本",
        )
        await self._send_contribution(
            event,
            kind=ContributionKind.WEEKLY,
            limit=limit or ContributionKind.WEEKLY.default_limit,
            format_type=format_type,
        )

    @error_reply
    @command_rate_limit(name="查日贡@")
    @registrar.on_group_command("查日贡@")
    async def check_daily_contribution_with_at(
        self,
        event: GroupMessageEvent,
    ) -> None:
        limit, _ = parse_format_and_limit(
            event.message.text,
            default_limit=ContributionKind.DAILY.default_limit,
        )
        await self._send_contribution_at(
            event,
            kind=ContributionKind.DAILY,
            limit=limit or ContributionKind.DAILY.default_limit,
        )

    @error_reply
    @command_rate_limit(name="查周贡@")
    @registrar.on_group_command("查周贡@")
    async def check_weekly_contribution_with_at(
        self,
        event: GroupMessageEvent,
    ) -> None:
        limit, _ = parse_format_and_limit(
            event.message.text,
            default_limit=ContributionKind.WEEKLY.default_limit,
        )
        await self._send_contribution_at(
            event,
            kind=ContributionKind.WEEKLY,
            limit=limit or ContributionKind.WEEKLY.default_limit,
        )

    async def _send_contribution(
        self,
        event: GroupMessageEvent,
        *,
        kind: ContributionKind,
        limit: int,
        format_type: str,
    ) -> None:
        user, army_id = await self.require_army(str(event.group_id))
        members = (await user.get_members(army_id)).filter(
            lambda m: kind.below_limit(m, limit)
        )
        if not members:
            await event.reply(f"太棒了！没有人{kind.label}低于 {limit}。")
            return

        if format_type == "图片":
            bind = await self.optional_bind(str(event.group_id), str(event.user_id))
            await self.replies.send_members(
                event,
                members,
                "图片",
                title=f"{kind.label}低于 {limit}",
                uid=bind.uid if bind else None,
            )
            return

        lines = [
            f"- {m.detail.playerName} (贡献: {kind.value_of(m)})"
            for m in members
        ]
        await self.replies.send_members(
            event,
            members,
            format_type,
            title=f"以下成员{kind.label}低于 {limit}：",
            file_prefix=kind.file_prefix,
            text_content=f"以下成员{kind.label}低于 {limit}：\n" + "\n".join(lines),
        )

    async def _send_contribution_at(
        self,
        event: GroupMessageEvent,
        *,
        kind: ContributionKind,
        limit: int,
    ) -> None:
        user, army_id = await self.require_army(str(event.group_id))
        members = (await user.get_members(army_id)).filter(
            lambda m: kind.below_limit(m, limit)
        )
        if not members:
            await event.reply(f"太棒了！没有人{kind.label}低于 {limit}。")
            return

        group_id = str(event.group_id)
        binds = await self.store.list_user_binds(group_id)
        uid_to_qq = {item.uid: item.qq_id for item in binds}
        group_members = await self.api.qq.query.get_group_member_list(event.group_id)
        group_qq_ids = {str(m.user_id) for m in group_members}
        exclude_list = set(await self.store.list_exclude(group_id))

        chain = MessageArray()
        chain.add_text(f"以下成员{kind.label}低于 {limit}：\n")
        for member in members:
            qq_id = uid_to_qq.get(str(member.uid))
            chain.add_text(f"- {member.detail.playerName} (贡献: {kind.value_of(member)}) ")
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
        await event.reply(rtf=chain)
