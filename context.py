from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.core.star.filter.custom_filter import CustomFilter
from bqyx_api.api import GameUser
from bqyx_api.archive import DemonWeekService
from bqyx_api.archive.player.service import PlayerBonusService
from bqyx_api.archive.things import MyThingsService
from bqyx_api.archive.union import UnionDefineService

from .account import AccountService
from .config import Settings
from .errors import ArmyNotBoundError, BotError
from .models import UserBind
from .parsing import parse_choice_index
from .reply import ReplyService, md_cmd_input
from .store import SqliteStore


@dataclass
class SessionResult:
    ok: bool
    text: str = ""
    timed_out: bool = False
    cancelled: bool = False


@dataclass
class MemberChoice:
    """包装多重名/模糊查询成功选中的目标成员对象。"""
    member: Any


def clean_reply_text(raw_text: str) -> str:
    """清理用户回复内容，剥离 [At:xxx] 标签、提及前缀以及首尾杂质字符。"""
    if not raw_text:
        return ""
    text = re.sub(r"\[At:[^\]]+\]", "", raw_text)
    text = re.sub(r"^@\S+\s*", "", text.strip())
    text = text.strip().lstrip("/#")
    return text.strip()


class PendingSessionFilter(CustomFilter):
    """过滤属于当前等待会话的消息。仅当 (group_id, sender_id) 存在待决会话时放行。"""

    def filter(self, event: AstrMessageEvent, cfg: Any = None) -> bool:
        group_id = str(event.get_group_id() or "")
        sender_id = str(event.get_sender_id() or "")
        return (group_id, sender_id) in BqyxServices._pending_sessions


class BqyxServices:
    """插件运行时依赖，给 handler mixin 提供类型提示与公共服务。"""

    settings: Settings
    store: SqliteStore
    account: AccountService
    replies: ReplyService
    things: MyThingsService
    player_bonus: PlayerBonusService
    union_defines: UnionDefineService
    demon_week: DemonWeekService

    # 存储处于等待输入状态的会话：(group_id, sender_id) -> Future[AstrMessageEvent]
    _pending_sessions: dict[tuple[str, str], asyncio.Future[AstrMessageEvent]] = {}

    def __getattr__(self, name: str) -> Any:
        if name == "replies":
            from pathlib import Path
            from .reply import ReplyService

            svc = ReplyService(Path("."))
            object.__setattr__(self, "replies", svc)
            return svc
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    async def require_army(self, group_id: str, qq_id: str = "") -> tuple[GameUser, int]:
        army_id = None
        if group_id:
            army_id = await self.store.get_group_army(str(group_id))
        elif qq_id:
            p_bind = await self.store.get_private_user_bind(str(qq_id))
            if p_bind:
                army_id = await self.store.get_user_army_id(p_bind.uid)
        if army_id is None:
            raise ArmyNotBoundError()
        user = await self.account.get_user()
        return user, army_id

    async def optional_bind(self, group_id: str, qq_id: str) -> UserBind | None:
        if not group_id:
            p_bind = await self.store.get_private_user_bind(str(qq_id))
            if p_bind:
                return UserBind(
                    group_id="",
                    qq_id=p_bind.qq_id,
                    uid=p_bind.uid,
                    arch_index=p_bind.arch_index,
                )
            return None
        return await self.store.get_user_bind(str(group_id), str(qq_id))

    async def wait_session_reply(
        self,
        event: AstrMessageEvent,
        *,
        timeout: float | None = None,
        cancel_words: list[str] | None = None,
    ) -> SessionResult:
        group_id = str(event.get_group_id() or "")
        sender_id = str(event.get_sender_id() or "")
        session_key = (group_id, sender_id)

        cancel_set = set(cancel_words or ["取消", "退出", "q", "Q"])
        wait_timeout = float(timeout or 30)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[AstrMessageEvent] = loop.create_future()

        # 如果同一用户已有未结束的等待会话，先取消旧的
        old_fut = self._pending_sessions.get(session_key)
        if old_fut and not old_fut.done():
            old_fut.cancel()

        self._pending_sessions[session_key] = future

        try:
            next_event = await asyncio.wait_for(future, timeout=wait_timeout)
            raw = (next_event.message_str or "").strip()
            text = clean_reply_text(raw)
            if text in cancel_set:
                return SessionResult(ok=False, cancelled=True)
            return SessionResult(ok=True, text=text)
        except (asyncio.TimeoutError, TimeoutError):
            return SessionResult(ok=False, timed_out=True)
        except asyncio.CancelledError:
            return SessionResult(ok=False, cancelled=True)
        except Exception as exc:
            return SessionResult(ok=False, text=str(exc))
        finally:
            if self._pending_sessions.get(session_key) is future:
                self._pending_sessions.pop(session_key, None)

    async def resolve_member_by_name(
        self,
        event: AstrMessageEvent,
        raw_members: Any,
        target_name: str,
        *,
        action: str = "查询",
    ) -> AsyncGenerator[MessageEventResult | Any, None]:
        """按角色名在军团成员中进行模糊查询，支持多重名未绑定/已绑定分类交互选择。

        若匹配单条成员，直接 yield 该 Member 对象并返回。
        若匹配多条成员，yield 提示消息并进入交互式回复，命中有效序号后 yield 选中的 Member 对象；
        若超时、取消或输入无效序号，yield 对应的提示/警告消息，不 yield Member 对象直接结束。
        """
        group_id = str(event.get_group_id() or "")
        sender_id = str(event.get_sender_id() or "")
        target_lower = target_name.strip().lower()

        matches = [
            m
            for m in raw_members
            if target_lower
            in (
                m.detail.playerName or ""
            ).lower()
        ]

        if not matches:
            raise BotError(f"未在本群军队中找到包含「{target_name}」的成员。")

        if len(matches) == 1:
            yield MemberChoice(matches[0])
            return

        # 存在重名或多个匹配角色时，查询本群绑定情况，分类展示未绑定和已绑定角色
        existing_binds = await self.store.list_user_binds(group_id)
        bound_map: dict[tuple[str, int], list[str]] = {}
        for b in existing_binds:
            key = (str(b.uid).strip(), int(b.arch_index))
            bound_map.setdefault(key, []).append(str(b.qq_id).strip())

        unbound_matches: list[Any] = []
        bound_matches: list[tuple[Any, list[str]]] = []
        for m in matches:
            m_uid = str(m.uid).strip()
            m_idx = int(m.index) if hasattr(m, "index") and m.index is not None else 0
            key = (m_uid, m_idx)
            if key in bound_map:
                bound_matches.append((m, bound_map[key]))
            else:
                unbound_matches.append(m)

        ordered_matches: list[Any] = []
        lines: list[str] = ["【未绑定】"]
        if unbound_matches:
            for m in unbound_matches:
                ordered_matches.append(m)
                idx = len(ordered_matches)
                p_name = m.detail.playerName or target_name
                contribution = m.contribution or 0
                lines.append(
                    f"{idx}. {md_cmd_input(p_name, str(idx))} (总贡献: {contribution:,})"
                )
        else:
            lines.append("（无）")

        lines.append("")

        lines.append("【已绑定】")
        if bound_matches:
            for m, qq_list in bound_matches:
                ordered_matches.append(m)
                idx = len(ordered_matches)
                p_name = m.detail.playerName or target_name
                contribution = m.contribution or 0
                if sender_id in qq_list:
                    bind_tag = " [当前你已绑定]"
                elif qq_list:
                    bind_tag = f" [已绑定 QQ: {', '.join(qq_list)}]"
                else:
                    bind_tag = " [已绑定]"
                lines.append(
                    f"{idx}. {md_cmd_input(p_name, str(idx))} (总贡献: {contribution:,}){bind_tag}"
                )
        else:
            lines.append("（无）")

        cancel_btn = md_cmd_input("取消", "取消")
        yield self.replies.markdown_tip(
            event,
            f"找到多个包含「{target_name}」的游戏角色，请回复序号进行{action}：",
            "\n".join(lines),
            f"30秒内有效，可直接点击角色名或回复序号；回复“取消”或点击 {cancel_btn} 退出",
        )

        result = await self.wait_session_reply(
            event,
            timeout=30,
            cancel_words=["取消", "退出", "q", "Q"],
        )

        if result.timed_out:
            yield self.replies.markdown_warn(event, f"等待超时，已退出{action}流程。")
            return
        if result.cancelled:
            yield self.replies.markdown_warn(event, f"已取消{action}。")
            return

        if result.ok:
            idx = parse_choice_index(result.text, len(ordered_matches))
            if idx is None and result.text:
                reply_name = result.text.strip().lower()
                matched_indices = [
                    i
                    for i, m in enumerate(ordered_matches, 1)
                    if (m.detail.playerName or "").strip().lower() == reply_name
                ]
                if len(matched_indices) == 1:
                    idx = matched_indices[0]

            if idx is None:
                err_msg = f"输入无效序号「{result.text or ''}」，{action}已取消。"
                yield self.replies.markdown_warn(event, err_msg)
                return

            yield MemberChoice(ordered_matches[idx - 1])
        else:
            err_msg = f"未收到有效回复，已退出{action}流程。"
            yield self.replies.markdown_warn(event, err_msg)

