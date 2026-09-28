from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from astrbot.api.event import AstrMessageEvent
from astrbot.core.utils.session_waiter import SessionController, session_waiter
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
        cancel_set = set(cancel_words or ["取消", "退出", "q", "Q"])
        wait_timeout = int(timeout or 30)
        future: asyncio.Future[SessionResult] = asyncio.Future()

        @session_waiter(timeout=wait_timeout)
        async def session_handler(
            controller: SessionController, next_event: AstrMessageEvent
        ) -> None:
            text = (next_event.message_str or "").strip()
            if text in cancel_set:
                controller.stop()
                if not future.done():
                    future.set_result(SessionResult(ok=False, cancelled=True))
                return

            controller.stop()
            if not future.done():
                future.set_result(SessionResult(ok=True, text=text))

        try:
            await session_handler(event)
            if future.done():
                return future.result()
            return SessionResult(ok=False, timed_out=True)
        except TimeoutError:
            return SessionResult(ok=False, timed_out=True)
        except Exception as exc:
            return SessionResult(ok=False, text=str(exc))
