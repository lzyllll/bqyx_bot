from __future__ import annotations

from bqyx_api.archive.things import MyThingsService
from ncatbot.plugin import NcatBotPlugin

from .account import AccountService
from .config import Settings, load_settings
from .handlers import BindHandlers, ExcludeHandlers, HelpHandlers, QueryHandlers, ThingsHandlers
from .reply import ReplyService
from .store import SqliteStore


class BqyxBotPlugin(
    NcatBotPlugin,
    HelpHandlers,
    BindHandlers,
    QueryHandlers,
    ThingsHandlers,
    ExcludeHandlers,
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
        self.store = SqliteStore(self.workspace / "bqyx.db")
        await self.store.init()
        self.account = AccountService(self.settings, self.store, self.logger)
        self.replies = ReplyService(self.api, self.workspace)
        self.things = MyThingsService.from_env(store_path=self.workspace / "archives")
        await self.account.warmup()
        self.logger.info("%s 已加载", self.name)

    async def on_close(self) -> None:
        await self.store.close()
        self.logger.info("%s 已卸载", self.name)
