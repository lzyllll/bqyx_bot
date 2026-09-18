import re

from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types import At, MessageArray

from ..context import BqyxServices
from ..errors import BotError, UserNotBoundError
from ..hooks import command_rate_limit, error_reply, my_dps_limit
from ..models import ContributionKind
from ..parsing import parse_format, parse_format_and_limit
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

        # 获取目标 QQ（若通过 @ 则使用被 @ 用户的 QQ，否则使用发送者 QQ）
        target_at = target
        if target_at is None and hasattr(event, "message") and event.message:
            for seg in event.message:
                if isinstance(seg, At):
                    target_at = seg
                    break

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
        view, summary = service.get_role_panel_and_bonus(
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
        result = self.demon_week.parse_archive(account)

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
