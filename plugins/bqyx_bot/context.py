from __future__ import annotations

from typing import Any

from bqyx_api.api import GameUser
from bqyx_api.archive.things import MyThingsService
from bqyx_api.archive.union import UnionDefineService

from .account import AccountService
from .config import Settings
from .errors import ArmyNotBoundError
from .models import UserBind
from .reply import ReplyService
from .store import SqliteStore


class BqyxServices:
    """插件运行时依赖，给 handler mixin 提供类型提示。"""

    settings: Settings
    store: SqliteStore
    account: AccountService
    replies: ReplyService
    things: MyThingsService
    api: Any
    _union_service: UnionDefineService | None

    async def require_army(self, group_id: str) -> tuple[GameUser, int]:
        army_id = await self.store.get_group_army(group_id)
        if army_id is None:
            raise ArmyNotBoundError()
        user = await self.account.get_user()
        return user, army_id

    async def optional_bind(self, group_id: str, qq_id: str) -> UserBind | None:
        return await self.store.get_user_bind(str(group_id), str(qq_id))

    def union_defines(self) -> UnionDefineService:
        service = getattr(self, "_union_service", None)
        if service is None:
            from bqyx_api.archive.paths import resource_dir

            service = UnionDefineService(resource_dir())
            self._union_service = service
        return service
