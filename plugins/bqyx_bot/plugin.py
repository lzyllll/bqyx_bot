from __future__ import annotations

import asyncio
from bqyx_api.archive import DemonWeekService
from bqyx_api.archive.player.service import PlayerBonusService
from bqyx_api.archive.things import MyThingsService
from bqyx_api.archive.union import UnionDefineService
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
    player_bonus: PlayerBonusService
    union_defines: UnionDefineService
    demon_week: DemonWeekService
    name = "bqyx_bot"
    version = "1.0.0"
    author = "lzy"
    description = "BQYX 军队查询与绑定"

    async def on_load(self) -> None:
        self.settings = load_settings()
        self.store = SqliteStore(
            self.workspace / "bqyx.db",
            retention_days=self.settings.snapshot_retention_days,
            union_retention_days=self.settings.union_snapshot_retention_days,
        )
        await self.store.init()
        self.account = AccountService(self.settings, self.store, self.logger)
        self.replies = ReplyService(self.api, self.workspace)
        # 服务所需资源、图标、快照及 TS 包默认参数均由 bqyx_api.archive.paths 集中管理，开箱即用
        self.things = MyThingsService()
        self.player_bonus = PlayerBonusService()
        self.union_defines = UnionDefineService()
        self.demon_week = DemonWeekService()
        await self.account.warmup()
        self._nightly_lock = asyncio.Lock()
        # 这里不仅仅是采集，采集后还会清理过期快照，避免占用过多空间
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

        # 指令每日清理
        if not self.add_scheduled_task(
            "prune_command_call_stats",
            "00:10",
            callback=self.prune_command_call_stats,
        ):
            self.logger.warning("注册 00:10 指令统计清理任务失败")
        self.logger.info("%s 已加载", self.name)

    async def on_close(self) -> None:
        if hasattr(self, "player_bonus") and self.player_bonus is not None:
            try:
                self.player_bonus.close()
            except Exception:
                pass
        await self.store.close()
        self.logger.info("%s 已卸载", self.name)
