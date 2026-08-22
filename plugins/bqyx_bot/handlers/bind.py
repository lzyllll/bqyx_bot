from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..bind_match import match_members
from ..context import BqyxServices
from ..errors import BotError, UserNotBoundError
from ..hooks import auto_bind_limit, error_reply, query_limit
from ..models import GameMember, QQMember


def pick_member_for_uid(members, uid: str):
    """在本群军队成员里按 UID 定位存档。0 个或多个存档都视为错误。"""
    matches = [member for member in members if str(member.uid) == str(uid)]
    if not matches:
        return None
    if len(matches) > 1:
        indexes = "、".join(str(member.index) for member in matches)
        raise BotError(
            f"该账号在本军有多个存档（{indexes}），请使用『绑定uid {uid} <存档0-7>』指定。"
        )
    return matches[0]


class BindHandlers(BqyxServices):
    @error_reply
    @registrar.on_group_command("绑定军队")
    async def bind_army(self, event: GroupMessageEvent, army_id: int) -> None:
        user = await self.account.get_user()
        union = await user.get_union_info(int(army_id))
        await self.store.set_group_army(str(event.group_id), int(army_id))
        name = getattr(union, "nickname", None) or getattr(union, "title", None) or army_id
        await event.reply(f"本群已成功绑定军队: {name} ({army_id})")

    @error_reply
    @registrar.on_group_command("绑定uid")
    async def bind_uid(
        self,
        event: GroupMessageEvent,
        uid: str,
        arch_index: int | None = None,
    ) -> None:
        uid = uid.strip()
        if not uid.isdigit():
            raise BotError("UID 必须是数字")

        resolved_index = arch_index
        if resolved_index is None:
            resolved_index = await self._lookup_arch_index(str(event.group_id), uid)
        if resolved_index is None:
            raise BotError("请指定存档编号：绑定uid <UID> <存档0-7>")
        if not 0 <= resolved_index <= 7:
            raise BotError("存档编号必须是 0-7")

        await self._save_bind(event, uid, resolved_index)


    @error_reply
    @registrar.on_group_command("绑定账号", "绑定用户名")
    async def bind_account(self, event: GroupMessageEvent, username: str) -> None:
        username = (username or "").strip()
        if not username:
            raise BotError("请输入 4399 账号名：绑定账号 <账号>")

        user, army_id = await self.require_army(str(event.group_id))
        try:
            uid = str(await user.get_uid_by_username(username)).strip()
        except BotError:
            raise
        except Exception as exc:
            detail = str(exc).strip()
            if "未能获取到有效的 UID" in detail or "用户名" in detail:
                raise BotError(f"找不到账号「{username}」，请确认 4399 用户名是否正确。") from exc
            raise BotError(f"查询账号失败：{detail or type(exc).__name__}") from exc

        if not uid.isdigit() or uid == "0":
            raise BotError(f"找不到账号「{username}」，请确认 4399 用户名是否正确。")

        try:
            members = await user.get_members(army_id)
        except Exception as exc:
            detail = str(exc).strip()
            raise BotError(f"获取本群军队成员失败：{detail or type(exc).__name__}") from exc

        member = pick_member_for_uid(members, uid)
        if member is None:
            raise BotError(
                f"账号「{username}」（UID {uid}）不在本群绑定的军队中，请确认账号或先绑定正确军队。"
            )

        player_name = getattr(getattr(member, "detail", None), "playerName", "") or ""
        await self._save_bind(
            event,
            uid,
            int(member.index),
            extra=f"账号 {username}" + (f" / 角色 {player_name}" if player_name else ""),
        )

    @error_reply
    @registrar.on_group_command("我的绑定")
    async def check_my_bind(self, event: GroupMessageEvent) -> None:
        bind = await self.store.get_user_bind(str(event.group_id), str(event.user_id))
        if not bind:
            raise UserNotBoundError()
        await event.reply(
            f"您已绑定游戏 UID: {bind.uid}，存档: {bind.arch_index}"
        )

    @error_reply
    @query_limit
    @registrar.on_group_command("我的信息")
    async def check_my_info(self, event: GroupMessageEvent) -> None:
        bind = await self.store.get_user_bind(str(event.group_id), str(event.user_id))
        if not bind:
            raise UserNotBoundError()

        user, army_id = await self.require_army(str(event.group_id))
        members = (await user.get_members(army_id)).filter(
            lambda m: str(m.uid) == bind.uid and int(m.index) == bind.arch_index
        )
        if not members:
            members = (await user.get_members(army_id)).filter(
                lambda m: str(m.uid) == bind.uid
            )
        if not members:
            raise BotError(f"未找到 UID {bind.uid} / 存档 {bind.arch_index} 的成员信息，请确认绑定是否正确。")

        member = members[0]
        await event.reply(
            "您的贡献信息：\n"
            f"名称：{member.detail.playerName}\n"
            f"UID：{member.uid}\n"
            f"存档：{member.index}\n"
            f"今日贡献：{member.detail.conDay}\n"
            f"本周贡献：{member.detail.conObj.this_week}\n"
            f"上周贡献: {member.detail.conObj.last_week}"
        )

    @error_reply
    @auto_bind_limit
    @registrar.on_group_command("一键绑定")
    async def auto_bind_uid(self, event: GroupMessageEvent) -> None:
        group_id = str(event.group_id)
        user, army_id = await self.require_army(group_id)

        group_members = await self.api.qq.query.get_group_member_list(int(group_id))
        qq_members = [
            QQMember(
                qq_id=str(member.user_id),
                nickname=(member.card or member.nickname or str(member.user_id)).strip(),
            )
            for member in group_members
            if "客串" not in (member.card or member.nickname or "")
        ]

        raw_game_members = await user.get_members(army_id)
        game_members = [
            GameMember(
                uid=str(member.uid),
                arch_index=int(member.index),
                nickname=str(member.detail.playerName).strip(),
            )
            for member in raw_game_members
            if getattr(member.detail, "playerName", None)
        ]

        await event.reply(
            f"开始规则匹配 {len(qq_members)} 个群成员和 {len(game_members)} 个游戏玩家..."
        )
        resolved, auto_lines, unmatched_games = match_members(qq_members, game_members)
        new_binds, updated_binds, unchanged_binds = await self.store.merge_user_binds(
            group_id,
            resolved,
        )
        sections = [
            "全量绑定完成",
            (
                f"总计: 自动匹配 {len(resolved)} 个，新增 {new_binds} 个，"
                f"更新 {updated_binds} 个，未变化 {unchanged_binds} 个"
            ),
        ]
        if auto_lines:
            sections.append("自动绑定：\n" + "\n".join(auto_lines))
        if unmatched_games:
            sections.append("未匹配游戏成员：\n" + "\n".join(unmatched_games))
        await self.replies.send_forward_text(event, "\n\n".join(sections))

    async def _save_bind(
        self,
        event: GroupMessageEvent,
        uid: str,
        arch_index: int,
        extra: str = "",
    ) -> None:
        qq_id = str(event.user_id)
        await self.store.set_user_bind(str(event.group_id), qq_id, uid, arch_index)
        suffix = f"（{extra}）" if extra else ""
        await event.reply(
            f"QQ {qq_id} 已绑定 UID {uid} / 存档 {arch_index}{suffix}"
        )

    async def _lookup_arch_index(self, group_id: str, uid: str) -> int | None:
        army_id = await self.store.get_group_army(group_id)
        if army_id is None:
            return None
        user = await self.account.get_user()
        members = await user.get_members(army_id)
        member = pick_member_for_uid(members, uid)
        return int(member.index) if member is not None else None
