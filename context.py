from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

from astrbot.api.event import AstrMessageEvent
from astrbot.core.star.filter.custom_filter import CustomFilter
from bqyx_api.api import GameUser
from bqyx_api.archive import DemonWeekService
from bqyx_api.archive.player.service import PlayerBonusService
from bqyx_api.archive.things import MyThingsService
from bqyx_api.archive.union import UnionDefineService

from .account import AccountService
from .config import Settings
from .errors import ArmyNotBoundError
from .models import UserBind
from .reply import ReplyService
from .store import SqliteStore


@dataclass
class SessionResult:
    ok: bool
    text: str = ""
    timed_out: bool = False
    cancelled: bool = False


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

    async def require_army(self, group_id: str) -> tuple[GameUser, int]:
        army_id = await self.store.get_group_army(str(group_id))
        if army_id is None:
            raise ArmyNotBoundError()
        user = await self.account.get_user()
        return user, army_id

    async def optional_bind(self, group_id: str, qq_id: str) -> UserBind | None:
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
