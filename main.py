from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 确保插件内置 lib/bqyx_api 在 sys.path 中
_PLUGIN_DIR = Path(__file__).resolve().parent
_LIB_DIR = _PLUGIN_DIR / "lib" / "bqyx_api"
if _LIB_DIR.exists() and str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from astrbot.api import AstrBotConfig, logger
from astrbot.api.star import Context, Star, register
from bqyx_api.archive import DemonWeekService
from bqyx_api.archive.player.service import PlayerBonusService
from bqyx_api.archive.things import MyThingsService
from bqyx_api.archive.union import UnionDefineService
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import astrbot.api.message_components as Comp
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
import functools
from astrbot.api.star import Context, Star, register
from astrbot.core.star.base import star_map
from astrbot.core.star.star_handler import star_handlers_registry


@register(
    "astrbot_plugin_bqyx",
    "lzy",
    "爆枪英雄 QQ 机器人：军队管理、成员数据与排行查询",
    "1.0.0",
    "https://github.com/lzyllll/bqyx_bot",
)
class BqyxBotPlugin(
    Star,
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

    def __init__(
        self, context: Context, config: AstrBotConfig | None = None
    ) -> None:
        super().__init__(context)
        self.config = config
        self.scheduler: AsyncIOScheduler | None = None
        self._nightly_lock = asyncio.Lock()

        plugin_metadata = star_map[self.__class__.__module__]
        # 关联元数据并将 self 绑定到各子模块的方法上
        for cls in (HelpHandlers, BindHandlers, QueryHandlers, ThingsHandlers, ExcludeHandlers, ScheduleHandlers, UnionRankHandlers):
            star_map[cls.__module__] = plugin_metadata
            for h in star_handlers_registry.get_handlers_by_module_name(cls.__module__):
                if not isinstance(h.handler, functools.partial):
                    h.handler = functools.partial(h.handler, self)

    async def initialize(self) -> None:
        self.settings = load_settings(self.config)

        # 数据存储在 AstrBot 插件数据目录下
        data_dir = _PLUGIN_DIR / "data"
        # try:
        #     from astrbot.core.utils.astrbot_path import get_astrbot_data_path

        #     data_dir = (
        #         get_astrbot_data_path() / "plugin_data" / "astrbot_plugin_bqyx"
        #     )
        # except Exception:
        #     pass
        data_dir.mkdir(parents=True, exist_ok=True)

        self.store = SqliteStore(
            data_dir / "bqyx.db",
            retention_days=self.settings.snapshot_retention_days,
            union_retention_days=self.settings.union_snapshot_retention_days,
        )
        await self.store.init()
        self.account = AccountService(self.settings, self.store, logger)
        self.replies = ReplyService(data_dir)
        self.things = MyThingsService()
        self.player_bonus = PlayerBonusService()
        self.union_defines = UnionDefineService()
        self.demon_week = DemonWeekService()

        # 预热代理账号
        await self.account.warmup()

        # 启动定时调度器 (Asia/Shanghai)
        self.scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
        self.scheduler.add_job(
            self.capture_members_and_cal_real,
            CronTrigger(hour=0, minute=1, timezone="Asia/Shanghai"),
            id="capture_members_and_cal_real",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.capture_unions,
            CronTrigger(hour=23, minute=59, timezone="Asia/Shanghai"),
            id="capture_unions",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.prune_command_call_stats,
            CronTrigger(hour=0, minute=10, timezone="Asia/Shanghai"),
            id="prune_command_call_stats",
            replace_existing=True,
        )
        self.scheduler.start()
        logger.info("astrbot_plugin_bqyx 插件已成功加载，定时任务已启动")

    

    async def terminate(self) -> None:
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        if hasattr(self, "player_bonus") and self.player_bonus is not None:
            try:
                self.player_bonus.close()
            except Exception:
                pass
        if hasattr(self, "store") and self.store is not None:
            await self.store.close()
        logger.info("astrbot_plugin_bqyx 插件已卸载")
