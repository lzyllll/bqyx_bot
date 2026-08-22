from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types import MessageArray

from ..context import BqyxServices
from ..hooks import error_reply, query_limit
from ..models import ContributionKind
from ..parsing import parse_format, parse_format_and_limit


class QueryHandlers(BqyxServices):
    @error_reply
    @query_limit
    @registrar.on_group_command("军队信息")
    async def check_union_info(self, event: GroupMessageEvent) -> None:
        format_type = parse_format(event.message.text, "图片")
        user, army_id = await self.require_army(str(event.group_id))
        union_info = await user.get_union_info(army_id)
        await self.replies.send_union_info(event, union_info, format_type)

    @error_reply
    @query_limit
    @registrar.on_group_command("查成员")
    async def check_members(self, event: GroupMessageEvent) -> None:
        format_type = parse_format(event.message.text, "图片")
        user, army_id = await self.require_army(str(event.group_id))
        members = (await user.get_members(army_id)).sort(
            key=lambda m: m.detail.conDay,
            reverse=True,
        )
        await self.replies.send_members(
            event,
            members,
            format_type,
            title="成员列表：",
            file_prefix="members",
        )

    @error_reply
    @query_limit
    @registrar.on_group_command("查争霸")
    async def check_domain(self, event: GroupMessageEvent) -> None:
        format_type = parse_format(event.message.text, "图片")
        user, army_id = await self.require_army(str(event.group_id))
        members = await user.get_members(army_id)
        union_info = await user.get_union_info(army_id)
        await self.replies.send_domain(event, members, union_info, format_type)

    @error_reply
    @query_limit
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
    @query_limit
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
    @query_limit
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
    @query_limit
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
            await self.replies.send_members(event, members, "图片")
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
