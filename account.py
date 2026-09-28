from __future__ import annotations

import asyncio
import logging

import aiohttp
from bqyx_api.api import GameUser
from bqyx_api.api.login import check_login

from .config import Settings
from .errors import AccountNotConfiguredError
from .store import SqliteStore


class AccountService:
    """用于查询军队数据的代理账号。"""

    def __init__(self, settings: Settings, store: SqliteStore, logger: logging.Logger) -> None:
        self.settings = settings
        self.store = store
        self.logger = logger
        self._user: GameUser | None = None
        self._lock = asyncio.Lock()

    async def warmup(self) -> None:
        try:
            await self.get_user()
        except Exception as exc:
            self.logger.warning("代理账号预热失败: %s", exc)

    async def get_user(self) -> GameUser:
        async with self._lock:
            if self._user is not None:
                return self._user

            session = await self.store.get_session()
            if session is not None:
                uid, cookies = session
                if await self._cookies_valid(cookies):
                    self.logger.info("使用已保存的代理账号 cookies")
                    self._user = GameUser(
                        uid=uid,
                        arch_index=self.settings.arch_index,
                        cookies=cookies,
                    )
                    return self._user
                self.logger.warning("已保存的 cookies 失效，准备重新登录")

            if not self.settings.username or not self.settings.password:
                raise AccountNotConfiguredError()

            self.logger.info("正在登录代理账号")
            user = await GameUser.login_account(
                self.settings.username,
                self.settings.password,
                arch_index=self.settings.arch_index,
            )
            user.change_arch_index(self.settings.arch_index)
            await self.store.set_session(user.uid, user.cookies)
            self._user = user
            return user

    async def _cookies_valid(self, cookies: dict[str, str]) -> bool:
        try:
            async with aiohttp.ClientSession(trust_env=False, cookies=cookies) as session:
                return bool(await check_login(session))
        except Exception as exc:
            self.logger.warning("cookie 校验失败: %s", exc)
            return False
