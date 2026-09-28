from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from bqyx_api.archive.union import UnionSave
from ..context import BqyxServices, MemberChoice, PendingSessionFilter
from ..errors import (
    ArmyNotBoundError,
    ArmyNotFoundError,
    BotError,
    GroupOnlyError,
    ParamError,
    UserNotBoundError,
    bqyx_error_to_bot_error,
    to_bot_error,
)
from ..hooks import command_rate_limit, error_reply, my_info_limit
from ..parsing import (
    extract_command_arg,
    extract_uid,
    parse_choice_index,
    parse_format,
)
from ..reply import md_cmd_example, md_cmd_input


def pick_member_for_uid(members: Any, uid: str) -> Any:
    """在本群军队成员里按 UID 定位存档。0 个或多个存档都视为错误。"""
    matches = [member for member in members if str(member.uid) == str(uid)]
    if not matches:
        return None
    if len(matches) > 1:
        indexes = "、".join(str(member.index) for member in matches)
        raise BotError(f"该账号在本军有多个存档（{indexes}），无法自动绑定。")
    return matches[0]


class BindHandlers(BqyxServices):
    @filter.custom_filter(PendingSessionFilter, priority=10000)
    async def handle_pending_session_reply(self, event: AstrMessageEvent) -> None:
        group_id = str(event.get_group_id() or "")
        sender_id = str(event.get_sender_id() or "")
        session_key = (group_id, sender_id)
        future = self._pending_sessions.get(session_key)
        if future is not None and not future.done():
            future.set_result(event)
            event.stop_event()

    @filter.command("绑定军队")
    @error_reply
    async def bind_army(self, event: AstrMessageEvent, army_id: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        clean_army_id = extract_command_arg(
            army_id, event, ("绑定军队",)
        ).strip()
        if not clean_army_id:
            tag = md_cmd_input("/绑定军队", "绑定军队")
            ex = md_cmd_example("/绑定军队 26490", "绑定军队 26490")
            tag_name = md_cmd_input("/绑定游戏名", "绑定游戏名")
            tag_uid = md_cmd_input("/绑定uid", "绑定uid")
            raise ParamError(
                "请输入军队ID",
                usage=f"{tag} `<军队ID>`",
                extra=f"例如：{ex}；如需绑定个人账号或角色，请使用 {tag_name} 或 {tag_uid}",
            )

        if not clean_army_id.isdigit():
            raise ParamError(
                "军队ID格式错误：请输入纯数字",
                usage="/绑定军队 <军队ID>",
                extra="例如：/绑定军队 26490",
            )

        target_army_id = int(clean_army_id)
        user = await self.account.get_user()
        try:
            union = await user.get_union_info(target_army_id)
        except Exception as e:
            bot_err = to_bot_error(e, army_id=target_army_id)
            if bot_err:
                raise bot_err
            raise BotError(f"绑定军队失败：{str(e)}")

        if not union:
            raise ArmyNotFoundError(target_army_id)

        army_name = (
            getattr(union, "title", None)
            or getattr(union, "nickname", None)
            or getattr(union, "name", None)
            or str(target_army_id)
        )
        await self.store.set_group_army(group_id, target_army_id)
        yield self.replies.markdown_success(
            event,
            f"本群已成功绑定军队: {army_name} ({target_army_id})",
        )

    @filter.command("绑定uid")
    @error_reply
    @command_rate_limit(name="绑定uid")
    async def bind_uid(self, event: AstrMessageEvent, uid: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        resolved_uid = extract_uid(uid) or extract_uid(event.message_str)
        if not resolved_uid:
            tag = md_cmd_input("/绑定uid", "绑定uid")
            raise ParamError(
                "请提供有效的游戏 UID",
                usage=f"{tag} `<UID>`",
                extra="例如 123456 或 123456_1",
            )

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            raise ArmyNotBoundError()
        user = await self.account.get_user()
        try:
            members = await user.get_members(army_id)
        except Exception as exc:
            detail = str(exc).strip()
            raise BotError(f"获取本群军队成员失败：{detail or type(exc).__name__}")

        member = pick_member_for_uid(members, resolved_uid)
        if member is None:
            raise BotError("未在本群军队中找到该成员，请确认 UID 或先绑定正确军队。")

        player_name = member.detail.playerName or ""
        qq_id = str(event.get_sender_id() or "")
        await self.store.set_user_bind(group_id, qq_id, resolved_uid, int(member.index))
        details = [f"UID: `{resolved_uid}`", f"存档: `{member.index}`"]
        if player_name:
            details.append(f"角色: `{player_name}`")
        yield self.replies.markdown_success(
            event,
            f"QQ {qq_id} 已成功绑定游戏角色",
            details,
        )

    @filter.command("绑定账号", alias={"绑定用户名"})
    @error_reply
    @command_rate_limit(name="绑定账号")
    async def bind_account(self, event: AstrMessageEvent, username: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        clean_username = extract_command_arg(
            username, event, ("绑定账号", "绑定用户名")
        )
        if not clean_username:
            tag = md_cmd_input("/绑定账号", "绑定账号")
            ex = md_cmd_example("/绑定账号 my_user", "绑定账号 my_user")
            raise ParamError(
                "请输入 4399 账号名",
                usage=f"{tag} `<账号>`",
                extra=f"例如：{ex}",
            )

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            raise ArmyNotBoundError()
        user = await self.account.get_user()
        try:
            uid = str(await user.get_uid_by_username(clean_username)).strip()
        except BotError:
            raise
        except Exception as exc:
            detail = str(exc).strip()
            if "未能获取到有效的 UID" in detail or "用户名" in detail:
                raise BotError(f"找不到账号「{clean_username}」，请确认 4399 用户名是否正确。")
            raise BotError(f"查询账号失败：{detail or type(exc).__name__}")

        if not uid.isdigit() or uid == "0":
            raise BotError(f"找不到账号「{clean_username}」，请确认 4399 用户名是否正确。")

        try:
            members = await user.get_members(army_id)
        except Exception as exc:
            detail = str(exc).strip()
            raise BotError(f"获取本群军队成员失败：{detail or type(exc).__name__}")

        member = pick_member_for_uid(members, uid)
        if member is None:
            raise BotError(f"账号「{clean_username}」不在本群绑定的军队中，请确认账号或先绑定正确军队。")

        player_name = member.detail.playerName or ""
        qq_id = str(event.get_sender_id() or "")
        await self.store.set_user_bind(group_id, qq_id, uid, int(member.index))
        details = [f"账号: `{clean_username}`", f"UID: `{uid}`", f"存档: `{member.index}`"]
        if player_name:
            details.append(f"角色: `{player_name}`")
        yield self.replies.markdown_success(
            event,
            f"QQ {qq_id} 已成功绑定游戏账号：{clean_username}",
            details,
        )

    @filter.command("绑定游戏名", alias={"绑定角色名", "绑定角色"})
    @error_reply
    @command_rate_limit(name="绑定游戏名")
    async def bind_game_name(self, event: AstrMessageEvent, name: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        target_name = extract_command_arg(
            name, event, ("绑定游戏名", "绑定角色名", "绑定角色")
        )
        if not target_name:
            tag = md_cmd_input("/绑定游戏名", "绑定游戏名")
            ex = md_cmd_example("/绑定游戏名 张三", "绑定游戏名 张三")
            raise ParamError(
                "请输入要绑定的游戏角色名",
                usage=f"{tag} `<角色名>`",
                extra=f"例如：{ex}（支持模糊匹配）",
            )

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            raise ArmyNotBoundError()
        user = await self.account.get_user()
        try:
            raw_members = await user.get_members(army_id)
        except Exception as exc:
            detail = str(exc).strip()
            raise BotError(f"获取本群军队成员失败：{detail or type(exc).__name__}")

        target_member = None
        async for item in self.resolve_member_by_name(
            event, raw_members, target_name, action="绑定"
        ):
            if isinstance(item, MemberChoice):
                target_member = item.member
            else:
                yield item

        if not target_member:
            return

        sender_id = str(event.get_sender_id() or "")
        player_name = target_member.detail.playerName or target_name
        await self.store.set_user_bind(
            group_id,
            sender_id,
            str(target_member.uid),
            int(target_member.index),
        )
        msg = f"QQ {sender_id} 已成功绑定游戏角色：{player_name}"
        yield self.replies.markdown_success(event, msg)

    @filter.command("我的绑定")
    @error_reply
    @command_rate_limit(name="我的绑定")
    async def check_my_bind(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        sender_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, sender_id)
        if not bind:
            raise UserNotBoundError()
        yield self.replies.markdown_success(
            event,
            f"已绑定角色信息",
            [f"UID: `{bind.uid}`", f"存档序号: `{bind.arch_index}`"],
        )

    @filter.command("我的信息")
    @error_reply
    @my_info_limit
    async def check_my_contribution(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        sender_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, sender_id)
        if not bind:
            raise UserNotBoundError()

        format_type = parse_format(event.message_str, "图片")
        user = await self.account.get_user()
        account = await user.get_account(bind.uid, bind.arch_index)
        union_data = self.union_defines.hydrate(
            UnionSave.from_archive(account.data),
            archive_time=account.datetime,
        )

        title = "我的贡献"
        army_id = await self.store.get_group_army(group_id)
        if army_id is not None:
            members = (await user.get_members(army_id)).filter(
                lambda m: str(m.uid) == bind.uid
            )
            if members:
                player_name = members[0].detail.playerName or ""
                if player_name:
                    title = f"{player_name} 的贡献"

        for res in await self.replies.build_contribution(
            event,
            union_data,
            format_type,
            title=title,
        ):
            yield res
