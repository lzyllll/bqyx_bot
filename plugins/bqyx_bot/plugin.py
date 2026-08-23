from __future__ import annotations

import asyncio

from bqyx_api.archive.paths import archive_store_dir, icon_dir, resource_dir
from bqyx_api.archive.things import MyThingsService
from ncatbot.plugin import NcatBotPlugin

from .account import AccountService
from .config import Settings, load_settings
from .handlers import (
    BindHandlers,
    ExcludeHandlers,
    HelpHandlers,
    QueryHandlers,
    ScheduleHandlers,
    ThingsHandlers,
    UnionRankHandlers,
)
from .reply import ReplyService
from .store import SqliteStore


class BqyxBotPlugin(
    NcatBotPlugin,
    HelpHandlers,
    BindHandlers,
    QueryHandlers,
    ThingsHandlers,
    ExcludeHandlers,
    ScheduleHandlers,
    UnionRankHandlers,
):
    settings: Settings
    store: SqliteStore
    account: AccountService
    replies: ReplyService
    things: MyThingsService
    name = "bqyx_bot"
    version = "1.0.0"
    author = "lzy"
    description = "BQYX 军队查询与绑定"

    async def on_load(self) -> None:
        self.settings = load_settings()
        self.store = SqliteStore(
            self.workspace / "bqyx.db",
            retention_days=self.settings.snapshot_retention_days,
        )
        await self.store.init()
        self.account = AccountService(self.settings, self.store, self.logger)
        self.replies = ReplyService(self.api, self.workspace)
        # 资源/图标/快照目录均从 .env 读取（BQYX_RESOURCE_DIR/BQYX_ASSETS_DIR/BQYX_ARCHIVE_STORE）
        self.things = MyThingsService(resource_dir(), icon_dir(), archive_store_dir())
        await self.account.warmup()
        self._nightly_lock = asyncio.Lock()
        if not self.add_scheduled_task(
            "capture_members",
            "23:30",
            callback=self.capture_members,
        ):
            self.logger.warning("注册 23:30 成员采集任务失败")
        if not self.add_scheduled_task(
            "capture_unions",
            "23:59",
            callback=self.capture_unions,
        ):
            self.logger.warning("注册 23:59 军队排行采集任务失败")
        self.logger.info("%s 已加载", self.name)

    async def on_close(self) -> None:
        await self.store.close()
        self.logger.info("%s 已卸载", self.name)
