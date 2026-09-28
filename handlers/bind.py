from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from bqyx_api.archive.union import UnionSave
from ..context import BqyxServices
from ..errors import BotError
from ..hooks import command_rate_limit, error_reply, my_info_limit
from ..parsing import (
    extract_command_arg,
    extract_uid,
    parse_choice_index,
    parse_format,
)


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
    @filter.command("绑定军队", alias={"绑定"})
    async def bind_army(self, event: AstrMessageEvent, army_id: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        clean_army_id = extract_command_arg(
            army_id, event, ("绑定军队", "绑定")
        ).strip()
        if not clean_army_id:
            yield self.replies.markdown_tip(
                event,
                "请输入军队ID",
                "/绑定军队 <军队ID>",
                "例如：/绑定军队 26490；如需绑定个人账号或角色，请使用 /绑定游戏名 或 /绑定uid",
            )
            return

        if not clean_army_id.isdigit():
            yield self.replies.markdown_warn(
                event,
                "军队ID格式错误：请输入纯数字，例如 /绑定军队 26490",
            )
            return

        target_army_id = int(clean_army_id)
        try:
            user = await self.account.get_user()
            union = await user.get_union_info(target_army_id)
            if not union:
                yield self.replies.markdown_warn(
                    event,
                    f"未查询到军队 ID {target_army_id} 的信息，请确认军队ID是否正确。",
                )
                return
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
        except Exception as e:
            logger.exception("绑定军队失败")
            yield self.replies.markdown_warn(event, f"绑定军队失败：{str(e)}")

    @error_reply
    @command_rate_limit(name="绑定uid")
    @filter.command("绑定uid")
    async def bind_uid(self, event: AstrMessageEvent, uid: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        resolved_uid = extract_uid(uid) or extract_uid(event.message_str)
        if not resolved_uid:
            yield self.replies.markdown_tip(
                event,
                "请提供有效的游戏 UID",
                "/绑定uid <UID>",
                "例如 123456 或 123456_1",
            )
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user = await self.account.get_user()
        members = await user.get_members(army_id)
        member = pick_member_for_uid(members, resolved_uid)
        if member is None:
            yield self.replies.markdown_warn(
                event,
                f"未在本群军队中找到该成员，请确认 UID（{resolved_uid}）或先绑定正确军队。",
            )
            return

        qq_id = str(event.get_sender_id() or "")
        await self.store.set_user_bind(group_id, qq_id, resolved_uid, int(member.index))
        player_name = getattr(getattr(member, "detail", None), "playerName", None) or resolved_uid
        yield self.replies.markdown_success(
            event,
            f"QQ {qq_id} 已成功绑定游戏角色：{player_name}",
            [f"UID: `{resolved_uid}`", f"存档: `{member.index}`"],
        )

    @error_reply
    @command_rate_limit(name="绑定账号")
    @filter.command("绑定账号", alias={"绑定用户名"})
    async def bind_account(self, event: AstrMessageEvent, username: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        clean_username = extract_command_arg(
            username, event, ("绑定账号", "绑定用户名")
        )
        if not clean_username:
            yield self.replies.markdown_tip(
                event,
                "请输入 4399 账号名",
                "/绑定账号 <账号>",
                "例如：/绑定账号 my_4399_name",
            )
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user = await self.account.get_user()
        try:
            uid = str(await user.get_uid_by_username(clean_username)).strip()
        except BotError:
            raise
        except Exception as exc:
            detail = str(exc).strip()
            if "未能获取到有效的 UID" in detail or "用户名" in detail:
                yield self.replies.markdown_warn(
                    event,
                    f"找不到账号「{clean_username}」，请确认 4399 用户名是否正确。",
                )
                return
            yield self.replies.markdown_warn(
                event, f"查询账号失败：{detail or type(exc).__name__}"
            )
            return

        if not uid.isdigit() or uid == "0":
            yield self.replies.markdown_warn(
                event,
                f"找不到账号「{clean_username}」，请确认 4399 用户名是否正确。",
            )
            return

        try:
            members = await user.get_members(army_id)
        except Exception as exc:
            detail = str(exc).strip()
            yield self.replies.markdown_warn(
                event,
                f"获取本群军队成员失败：{detail or type(exc).__name__}",
            )
            return

        member = pick_member_for_uid(members, uid)
        if member is None:
            yield self.replies.markdown_warn(
                event,
                f"账号「{clean_username}」不在本群绑定的军队中，请确认账号或先绑定正确军队。",
            )
            return

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

    @error_reply
    @command_rate_limit(name="绑定游戏名")
    @filter.command("绑定游戏名", alias={"绑定角色名", "绑定角色"})
    async def bind_game_name(self, event: AstrMessageEvent, name: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        target_name = extract_command_arg(
            name, event, ("绑定游戏名", "绑定角色名", "绑定角色")
        )
        if not target_name:
            yield self.replies.markdown_tip(
                event,
                "请输入要绑定的游戏角色名",
                "/绑定游戏名 <角色名>",
                "例如：/绑定游戏名 张三（支持模糊匹配）",
            )
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            yield self.replies.markdown_tip(
                event,
                "当前群尚未绑定军队",
                "/绑定军队 <军队ID>",
                "请管理员先使用：/绑定军队 1234",
            )
            return
        user = await self.account.get_user()
        try:
            raw_members = await user.get_members(army_id)
        except Exception as exc:
            detail = str(exc).strip()
            yield self.replies.markdown_warn(
                event,
                f"获取本群军队成员失败：{detail or type(exc).__name__}",
            )
            return

        target_lower = target_name.lower()
        matches = [
            m
            for m in raw_members
            if target_lower in (m.detail.playerName or "").lower()
        ]

        if not matches:
            yield self.replies.markdown_warn(
                event,
                f"未在本群军队中找到包含「{target_name}」的成员。",
            )
            return

        sender_id = str(event.get_sender_id() or "")
        if len(matches) == 1:
            target_member = matches[0]
            player_name = target_member.detail.playerName or target_name
            await self.store.set_user_bind(
                group_id,
                sender_id,
                str(target_member.uid),
                int(target_member.index),
            )
            msg = f"QQ {sender_id} 已成功绑定游戏角色：{player_name}"
            yield self.replies.markdown_success(event, msg)
            return

        lines = [
            f"{i}. {m.detail.playerName} (总贡献: {m.contribution:,})"
            for i, m in enumerate(matches, 1)
        ]

        yield self.replies.markdown_tip(
            event,
            f"找到多个包含「{target_name}」的游戏角色，请回复序号进行绑定：",
            "\n".join(lines),
            "30秒内有效，回复“取消”退出",
        )

        result = await self.wait_session_reply(
            event,
            timeout=30,
            cancel_words=["取消", "退出", "q", "Q"],
        )

        if result.timed_out:
            yield self.replies.markdown_warn(event, "等待超时，已退出绑定流程。")
            return
        if result.cancelled:
            yield self.replies.markdown_warn(event, "已取消绑定。")
            return

        if result.ok:
            idx = parse_choice_index(result.text, len(matches))
            if idx is None:
                err_msg = f"输入无效序号「{result.text or ''}」，绑定已取消。"
                yield self.replies.markdown_warn(event, err_msg)
                return

            target_member = matches[idx - 1]
            player_name = target_member.detail.playerName or target_name
            await self.store.set_user_bind(
                group_id,
                sender_id,
                str(target_member.uid),
                int(target_member.index),
            )
            msg = f"QQ {sender_id} 已成功绑定游戏角色：{player_name}"
            yield self.replies.markdown_success(event, msg)
        else:
            err_msg = "未收到有效回复，已退出绑定流程。"
            yield self.replies.markdown_warn(event, err_msg)

    @error_reply
    @command_rate_limit(name="我的绑定")
    @filter.command("我的绑定")
    async def check_my_bind(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        sender_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, sender_id)
        if not bind:
            yield self.replies.markdown_tip(
                event,
                "你尚未在本群绑定游戏角色",
                "/绑定游戏名 <角色名> 或 /绑定uid <UID>",
                "示例：/绑定游戏名 张三 或 /绑定uid 123456",
            )
            return
        yield self.replies.markdown_success(
            event,
            f"已绑定角色信息",
            [f"UID: `{bind.uid}`", f"存档序号: `{bind.arch_index}`"],
        )

    @error_reply
    @my_info_limit
    @filter.command("我的信息")
    async def check_my_contribution(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            yield self.replies.markdown_warn(event, "该指令仅支持在群聊中使用。")
            return

        sender_id = str(event.get_sender_id() or "")
        bind = await self.store.get_user_bind(group_id, sender_id)
        if not bind:
            yield self.replies.markdown_tip(
                event,
                "你尚未在本群绑定游戏角色",
                "/绑定游戏名 <角色名> 或 /绑定uid <UID>",
                "例如：/绑定游戏名 张三",
            )
            return

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
