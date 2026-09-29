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

    @filter.command("切换账号", alias={"选择账号", "切换角色", "换绑", "选择角色"})
    @error_reply
    async def switch_account(self, event: AstrMessageEvent):
        """私聊中切换已绑定的游戏账号。"""
        async for res in self._show_account_selector(event):
            yield res

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def on_private_message(self, event: AstrMessageEvent):
        """私人聊天消息适配：
        - 若用户发送切换账号指令，进入选择器流程；
        - 若尚未持久化绑定私聊账号，进入选择器引导流程；
        - 若已持久化绑定：
          - 若为已知指令，直接放行给各指令 handler 执行；
          - 若为非指令普通消息，展示当前绑定角色卡片与快捷指令/切换账号按钮。
        """
        qq_id = str(event.get_sender_id() or "")
        if not qq_id:
            return

        msg_str = (event.message_str or "").strip()
        if not msg_str:
            return

        # 若以指令前缀 / 或 # 开头，直接放行给指令系统处理
        if msg_str.startswith(("/", "#")):
            return

        cmd_body = msg_str.lstrip("/#").strip()
        cmd_lower = cmd_body.lower()

        # 1. 检查是否为切换账号/换绑指令
        is_switch_cmd = any(
            cmd_body.startswith(k)
            for k in ("切换账号", "选择账号", "切换角色", "换绑", "选择角色")
        ) or (cmd_body in ("绑定", "换号"))

        # 2. 查询当前是否已持久化绑定
        current_bind = await self.store.get_private_user_bind(qq_id)

        # 3. 如果是切换指令，或者尚未绑定过任何账号，进入选择器流程
        if is_switch_cmd or current_bind is None:
            async for res in self._show_account_selector(event):
                yield res
            return

        # 4. 如果已经绑定过，且当前输入是其它指令（涵盖排行、个人、军队、统计等全部指令），放行给具体 handler 处理，绝不弹窗打扰！
        command_prefixes = (
            # 基础与个人
            "我的", "查", "帮助", "help", "统计", "绑定", "免at",
            "战力", "贡献", "日贡", "周贡", "物品", "修罗", "争霸", "成员",
            # 排行与军队相关
            "今日", "昨日", "实时", "本周", "上周", "军队", "排行",
            # 英文指令
            "union", "members", "domain", "pk", "dps",
        )
        if any(cmd_lower.startswith(p) for p in command_prefixes):
            return

        # 5. 如果是普通打招呼或其它消息，回复当前绑定的角色状态卡片和快捷按钮
        p_name = current_bind.player_name or f"UID_{current_bind.uid}"
        btn_switch = md_cmd_example("切换账号", "切换账号")
        btn_info = md_cmd_example("我的信息", "我的信息")
        btn_daily = md_cmd_example("我的日贡", "我的日贡")
        btn_dps = md_cmd_example("我的战力", "我的战力")
        btn_things = md_cmd_example("我的物品", "我的物品")
        btn_rank = md_cmd_example("今日日贡排行", "今日日贡排行")

        card_md = (
            f"> 💡 **爆枪英雄私聊助手**\n"
            f"> 当前绑定角色：**{p_name}** (UID: `{current_bind.uid}`, 存档: `{current_bind.arch_index}`)\n"
            f">\n"
            f"> 快捷功能（点击填入）：\n"
            f"> • {btn_info}　• {btn_daily}\n"
            f"> • {btn_dps}　• {btn_things}\n"
            f"> • {btn_rank}　• {btn_switch}\n"
            f">\n"
            f"> 💬 如需更换绑定的角色，请点击上方 {btn_switch}。"
        )
        yield self.replies.markdown_result(event, card_md)

    async def _show_account_selector(self, event: AstrMessageEvent):
        """展示所有候选账号列表并等待用户选择绑定。"""
        qq_id = str(event.get_sender_id() or "")
        if not qq_id:
            return

        # 获取该 QQ 关联的所有游戏账号 (uid, arch_index, player_name)
        accounts_raw = await self.store.list_accounts_by_qq(qq_id)
        if not accounts_raw:
            tag_name = md_cmd_input("/绑定游戏名", "绑定游戏名")
            tag_uid = md_cmd_input("/绑定uid", "绑定uid")
            md_text = (
                "> 💡 **私聊账号绑定**\n"
                f"> 未查询到与 QQ `{qq_id}` 关联的游戏账号。\n"
                f"> 请先在已加入的军队群中使用 {tag_name} 或 {tag_uid} 绑定角色，之后即可在私聊中选择切换绑定账号。"
            )
            yield self.replies.markdown_result(event, md_text)
            return

        accounts: list[tuple[str, int, str]] = []
        user = None
        for uid, arch_index, p_name in accounts_raw:
            final_name = p_name
            if not final_name:
                try:
                    if user is None:
                        user = await self.account.get_user()
                    acc = await user.get_account(uid, arch_index)
                    final_name = getattr(acc, "title", None) or f"UID_{uid}"
                except Exception:
                    final_name = f"UID_{uid}"
            accounts.append((uid, arch_index, final_name))

        current_bind = await self.store.get_private_user_bind(qq_id)

        lines = []
        for i, (uid, arch_index, name) in enumerate(accounts, 1):
            is_current = (
                current_bind is not None
                and current_bind.uid == uid
                and current_bind.arch_index == arch_index
            )
            current_tag = " `[当前已绑定]`" if is_current else ""
            btn = md_cmd_input(name, str(i))
            lines.append(f"> {i}. {btn} (UID: `{uid}`, 存档: `{arch_index}`){current_tag}")

        cancel_btn = md_cmd_input("取消", "取消")
        selector_md = (
            f"> 💡 **私聊游戏账号选择 (共 {len(accounts)} 个)**\n"
            f"> 检测到与您 QQ 关联的账号，请回复序号进行绑定：\n"
            f">\n"
            + "\n".join(lines)
            + "\n>\n"
            f"> 💬 30秒内回复序号（如 1）或点击角色名选择，回复“取消”或点击 {cancel_btn} 退出。"
        )
        yield self.replies.markdown_result(event, selector_md)

        session_res = await self.wait_session_reply(
            event,
            timeout=30,
            cancel_words=["取消", "退出", "q", "Q"],
        )

        if session_res.cancelled:
            yield self.replies.markdown_warn(event, "已取消私聊账号选择。")
            return
        if session_res.timed_out:
            yield self.replies.markdown_warn(event, "等待选择超时，已自动退出。")
            return
        if not session_res.ok:
            return

        choice_idx = parse_choice_index(session_res.text, len(accounts))
        choice = (choice_idx - 1) if choice_idx is not None else None
        if choice is None and session_res.text:
            reply_name = session_res.text.strip().lower()
            for idx, (_, _, a_name) in enumerate(accounts):
                if a_name.strip().lower() == reply_name:
                    choice = idx
                    break

        if choice is None:
            yield self.replies.markdown_warn(
                event, f"输入序号「{session_res.text}」无效，已退出选择。"
            )
            return

        selected_uid, selected_arch, selected_name = accounts[choice]
        await self.store.set_private_user_bind(
            qq_id, selected_uid, selected_arch, selected_name
        )
        btn_switch = md_cmd_example("切换账号", "切换账号")
        yield self.replies.markdown_success(
            event,
            f"私聊已成功绑定角色：{selected_name}",
            [
                f"UID: `{selected_uid}`",
                f"存档序号: `{selected_arch}`",
                f"已持久化保存，后续可直接使用查询指令；如需换绑请发送 {btn_switch}",
            ],
        )

    @filter.command("绑定军队")
    @error_reply
    async def bind_army(self, event: AstrMessageEvent, army_id: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            tag_name = md_cmd_input("绑定游戏名", "绑定游戏名")
            tag_switch = md_cmd_example("切换账号", "切换账号")
            raise BotError(f"私聊无需绑定军队。如需绑定或切换角色，请使用 {tag_name} 或 {tag_switch}。")

        clean_army_id = extract_command_arg(
            army_id, event, ("绑定军队",)
        ).strip()
        if not clean_army_id:
            tag = md_cmd_input("/绑定军队", "绑定军队")
            ex = md_cmd_example("/绑定军队 26490", "绑定军队 26490")
            tag_name = md_cmd_input("/绑定游戏名", "绑定游戏名")
            tag_all = md_cmd_example("/绑定游戏名 ~", "绑定游戏名 ~")
            tag_uid = md_cmd_input("/绑定uid", "绑定uid")
            raise ParamError(
                "请输入军队ID",
                usage=f"{tag} `<军队ID>`",
                extra=f"例如：{ex}；如需绑定个人账号或角色，请使用 {tag_name} 或 {tag_all} 或 {tag_uid}",
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
        qq_id = str(event.get_sender_id() or "")

        resolved_uid = extract_uid(uid) or extract_uid(event.message_str)
        if not resolved_uid:
            tag = md_cmd_input("/绑定uid", "绑定uid")
            raise ParamError(
                "请提供有效的游戏 UID",
                usage=f"{tag} `<UID>`",
                extra="例如 123456 或 123456_1",
            )

        if not group_id:
            user = await self.account.get_user()
            player_name = f"UID_{resolved_uid}"
            try:
                acc = await user.get_account(resolved_uid, 0)
                player_name = getattr(acc, "title", None) or player_name
            except Exception:
                pass
            await self.store.set_private_user_bind(qq_id, resolved_uid, 0, player_name)
            btn_switch = md_cmd_example("切换账号", "切换账号")
            yield self.replies.markdown_success(
                event,
                f"私聊已成功绑定游戏角色：{player_name}",
                [f"UID: `{resolved_uid}`", "存档: `0`", f"如需切换账号请点击 {btn_switch}"],
            )
            return

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
        qq_id = str(event.get_sender_id() or "")

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

        if not group_id:
            player_name = clean_username
            try:
                acc = await user.get_account(uid, 0)
                player_name = getattr(acc, "title", None) or clean_username
            except Exception:
                pass
            await self.store.set_private_user_bind(qq_id, uid, 0, player_name)
            btn_switch = md_cmd_example("切换账号", "切换账号")
            yield self.replies.markdown_success(
                event,
                f"私聊已成功绑定游戏账号：{clean_username}",
                [f"UID: `{uid}`", f"角色: `{player_name}`", f"如需切换账号请点击 {btn_switch}"],
            )
            return

        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            raise ArmyNotBoundError()
        try:
            members = await user.get_members(army_id)
        except Exception as exc:
            detail = str(exc).strip()
            raise BotError(f"获取本群军队成员失败：{detail or type(exc).__name__}")

        member = pick_member_for_uid(members, uid)
        if member is None:
            raise BotError(f"账号「{clean_username}」不在本群绑定的军队中，请确认账号或先绑定正确军队。")

        player_name = member.detail.playerName or ""
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
        sender_id = str(event.get_sender_id() or "")

        target_name = extract_command_arg(
            name, event, ("绑定游戏名", "绑定角色名", "绑定角色")
        ).strip()

        # 私聊直接调起账号选择器或根据输入绑定
        if not group_id:
            if not target_name or target_name in ("~", "～"):
                async for res in self._show_account_selector(event):
                    yield res
                return
            accounts_raw = await self.store.list_accounts_by_qq(sender_id)
            target_lower = target_name.lower()
            matched = [
                acc for acc in accounts_raw
                if (acc[2] and target_lower in acc[2].lower())
            ]
            if matched:
                selected_uid, selected_arch, selected_name = matched[0]
                await self.store.set_private_user_bind(
                    sender_id, selected_uid, selected_arch, selected_name
                )
                yield self.replies.markdown_success(
                    event,
                    f"私聊已成功绑定游戏角色：{selected_name}",
                    [f"UID: `{selected_uid}`", f"存档: `{selected_arch}`"],
                )
                return
            async for res in self._show_account_selector(event):
                yield res
            return

        target_name = extract_command_arg(
            name, event, ("绑定游戏名", "绑定角色名", "绑定角色")
        ).strip()
        if not target_name:
            tag = md_cmd_input("/绑定游戏名", "绑定游戏名")
            ex = md_cmd_example("/绑定游戏名 张三", "绑定游戏名 张三")
            tag_all = md_cmd_example("绑定游戏名 ~", "绑定游戏名 ~")
            raise ParamError(
                "请输入要绑定的游戏角色名",
                usage=f"{tag} `<角色名>` 或 {tag_all}",
                extra=f"• 方式1：{ex}（支持模糊匹配）\n• 方式2：输入 {tag_all} 列出全军团成员直接点击绑定",
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

        if target_name in ("~", "～"):
            yield self._render_all_members_for_bind(event, raw_members)
            return

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

    def _render_all_members_for_bind(
        self,
        event: AstrMessageEvent,
        members: Any,
    ):
        member_list = list(members)
        if not member_list:
            raise BotError("当前军队暂无成员数据。")

        # 先按总贡献降序，再按日贡献降序，直接使用对象属性访问
        sorted_members = sorted(
            member_list,
            key=lambda m: (
                int(m.contribution or 0),
                int(m.detail.conDay or 0),
            ),
            reverse=True,
        )

        lines = []
        for i, m in enumerate(sorted_members, 1):
            p_name = m.detail.playerName or f"UID_{m.uid}"
            # 点击后把 绑定游戏名 xxx 填入输入框
            link = md_cmd_example(p_name, f"绑定游戏名 {p_name}")
            lines.append(f"{i:02d}. {link}")

        tip_lines = [
            f"> 💡 **军团成员快捷绑定 (共 {len(sorted_members)} 人)**",
            "> 点击下方蓝色游戏名，自动填入绑定指令：",
            "> ",
        ]
        tip_lines.extend(f"> {line}" for line in lines)
        return self.replies.markdown_result(event, "\n".join(tip_lines))

    @filter.command("我的绑定")
    @error_reply
    @command_rate_limit(name="我的绑定")
    async def check_my_bind(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        sender_id = str(event.get_sender_id() or "")
        if not group_id:
            p_bind = await self.store.get_private_user_bind(sender_id)
            if not p_bind:
                raise UserNotBoundError()
            details = [f"UID: `{p_bind.uid}`", f"存档序号: `{p_bind.arch_index}`"]
            if p_bind.player_name:
                details.append(f"角色: `{p_bind.player_name}`")
            yield self.replies.markdown_success(
                event,
                "私聊已绑定角色信息",
                details,
            )
            return

        bind = await self.store.get_user_bind(group_id, sender_id)
        if not bind:
            raise UserNotBoundError()
        yield self.replies.markdown_success(
            event,
            "已绑定角色信息",
            [f"UID: `{bind.uid}`", f"存档序号: `{bind.arch_index}`"],
        )

    @filter.command("我的信息")
    @error_reply
    @my_info_limit
    async def check_my_contribution(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        sender_id = str(event.get_sender_id() or "")
        saved_name = None
        if not group_id:
            p_bind = await self.store.get_private_user_bind(sender_id)
            if not p_bind:
                raise UserNotBoundError()
            bind_uid = p_bind.uid
            bind_arch = p_bind.arch_index
            saved_name = p_bind.player_name
        else:
            bind = await self.store.get_user_bind(group_id, sender_id)
            if not bind:
                raise UserNotBoundError()
            bind_uid = bind.uid
            bind_arch = bind.arch_index

        format_type = parse_format(event.message_str, "图片")
        user = await self.account.get_user()
        account = await user.get_account(bind_uid, bind_arch)
        union_data = self.union_defines.hydrate(
            UnionSave.from_archive(account.data),
            archive_time=account.datetime,
        )

        title = "我的贡献"
        if saved_name:
            title = f"{saved_name} 的贡献"
        elif group_id:
            army_id = await self.store.get_group_army(group_id)
            if army_id is not None:
                members = (await user.get_members(army_id)).filter(
                    lambda m: str(m.uid) == bind_uid
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
