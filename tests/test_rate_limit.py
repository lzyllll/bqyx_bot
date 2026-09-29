from types import SimpleNamespace
from typing import Any

import pytest
from astrbot_plugin_bqyx.handlers.help import HelpHandlers
from astrbot_plugin_bqyx.hooks import GroupRateLimiter, command_rate_limit, total_call_limit
from astrbot_plugin_bqyx.reply import ReplyService


class FakeEvent:
    def __init__(self, group_id: str = "100") -> None:
        self.group_id = group_id
        self.replies: list[str] = []

    def get_group_id(self) -> str:
        return self.group_id

    async def send(self, message: Any) -> None:
        msg = ""
        for comp in getattr(message, "chain", []):
            if hasattr(comp, "text"):
                msg += comp.text
        self.replies.append(msg or str(message))

    async def reply(self, text: str) -> None:
        self.replies.append(text)


class FakeCommandStatsStore:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def record_command_call(self, command_name: str) -> None:
        self.counts[command_name] = self.counts.get(command_name, 0) + 1

    async def list_command_call_stats(self) -> list[tuple[str, int]]:
        return sorted(self.counts.items(), key=lambda item: (-item[1], item[0]))


@pytest.mark.asyncio
async def test_rate_limit_warns_once_then_ignores():
    limiter = GroupRateLimiter(max_calls=1, period=60)
    event = FakeEvent()

    @limiter
    async def handler(self, event):
        return "ok"

    # 限流已取消，多次连续调用均正常放行，不被拦截
    assert await handler(SimpleNamespace(), event) == "ok"
    assert event.replies == []

    assert await handler(SimpleNamespace(), event) == "ok"
    assert event.replies == []

    assert await handler(SimpleNamespace(), event) == "ok"
    assert event.replies == []


@pytest.mark.asyncio
async def test_rate_limit_keeps_blocking_while_still_asking(monkeypatch):
    limiter = GroupRateLimiter(max_calls=1, period=10)
    event = FakeEvent()
    clock = {"now": 100.0}
    monkeypatch.setattr("astrbot_plugin_bqyx.hooks.time.monotonic", lambda: clock["now"])

    @limiter
    async def handler(self, event):
        return "ok"

    # 限流已取消，任何时间点均正常放行
    assert await handler(SimpleNamespace(), event) == "ok"

    clock["now"] = 100.1
    assert await handler(SimpleNamespace(), event) == "ok"

    clock["now"] = 109.0
    assert await handler(SimpleNamespace(), event) == "ok"

    clock["now"] = 109.5
    assert await handler(SimpleNamespace(), event) == "ok"
    assert event.replies == []


def test_rate_limiter_name_prefixes_key():
    limiter = GroupRateLimiter(max_calls=1, period=60, name="今日日贡")
    assert limiter._key(FakeEvent("100")) == "今日日贡:100"
    plain = GroupRateLimiter(max_calls=1, period=60)
    assert plain._key(FakeEvent("100")) == "100"
    assert limiter._key(FakeEvent(group_id=None)) is None


@pytest.mark.asyncio
async def test_command_limits_are_per_command_and_share_global_rpm(monkeypatch):
    total_call_limit.reset()
    monkeypatch.setattr("astrbot_plugin_bqyx.hooks.time.monotonic", lambda: 100.0)

    first_event = FakeEvent()
    second_event = FakeEvent()

    @command_rate_limit()
    async def first_handler(self, event):
        return "first"

    @command_rate_limit()
    async def second_handler(self, event):
        return "second"

    assert await first_handler(SimpleNamespace(), first_event) == "first"
    assert await second_handler(SimpleNamespace(), second_event) == "second"
    assert total_call_limit.calls_in_period() == 2

    # 限流已取消：多次调用均成功放行且不返回 None，不回复限流警告
    assert await first_handler(SimpleNamespace(), first_event) == "first"
    assert await first_handler(SimpleNamespace(), first_event) == "first"
    assert first_event.replies == []
    assert total_call_limit.calls_in_period() == 4

    total_call_limit.reset()


@pytest.mark.asyncio
async def test_command_rate_limit_supports_the_five_second_my_info_exception(
    monkeypatch,
):
    total_call_limit.reset()
    clock = {"now": 100.0}
    monkeypatch.setattr("astrbot_plugin_bqyx.hooks.time.monotonic", lambda: clock["now"])
    event = FakeEvent()

    @command_rate_limit(max_calls=1, period=5, name="我的信息")
    async def my_info_handler(self, event):
        return "ok"

    # 限流已取消：无需等待 5 秒即可连续调用
    assert await my_info_handler(SimpleNamespace(), event) == "ok"
    clock["now"] = 100.1
    assert await my_info_handler(SimpleNamespace(), event) == "ok"
    clock["now"] = 104.9
    assert await my_info_handler(SimpleNamespace(), event) == "ok"
    assert event.replies == []
    total_call_limit.reset()


@pytest.mark.asyncio
async def test_global_rpm_limit_warns_each_group_once(monkeypatch):
    total_call_limit.reset()
    monkeypatch.setattr(total_call_limit, "max_calls", 1)
    monkeypatch.setattr("astrbot_plugin_bqyx.hooks.time.monotonic", lambda: 100.0)

    first_event = FakeEvent("100")
    second_event = FakeEvent("200")

    @command_rate_limit(max_calls=5, period=60)
    async def handler(self, event):
        return "ok"

    # 限流已取消：全局限制不拦截任何群
    assert await handler(SimpleNamespace(), first_event) == "ok"
    assert await handler(SimpleNamespace(), second_event) == "ok"
    assert second_event.replies == []
    assert total_call_limit.calls_in_period() == 2

    total_call_limit.reset()


@pytest.mark.asyncio
async def test_rpm_command_reports_the_current_global_window(monkeypatch, tmp_path):
    total_call_limit.reset()
    monkeypatch.setattr("astrbot_plugin_bqyx.hooks.time.monotonic", lambda: 100.0)
    event = FakeEvent()

    handler = HelpHandlers()
    handler.replies = ReplyService(workspace=tmp_path)
    await handler.show_rpm(event)

    assert event.replies == ["当前全局 RPM：1/30"]
    total_call_limit.reset()


@pytest.mark.asyncio
async def test_command_stats_record_only_calls_that_pass_both_limits(monkeypatch):
    total_call_limit.reset()
    monkeypatch.setattr("astrbot_plugin_bqyx.hooks.time.monotonic", lambda: 100.0)
    event = FakeEvent()
    store = FakeCommandStatsStore()

    @command_rate_limit(name="测试指令")
    async def handler(self, event):
        return "ok"

    plugin = SimpleNamespace(store=store)
    assert await handler(plugin, event) == "ok"
    assert await handler(plugin, event) == "ok"
    assert await handler(plugin, event) == "ok"
    assert store.counts == {"测试指令": 3}
    total_call_limit.reset()


@pytest.mark.asyncio
async def test_daily_command_stats_include_the_stats_command(monkeypatch, tmp_path):
    total_call_limit.reset()
    monkeypatch.setattr("astrbot_plugin_bqyx.hooks.time.monotonic", lambda: 100.0)
    event = FakeEvent()
    handler = HelpHandlers()
    handler.replies = ReplyService(workspace=tmp_path)
    handler.store = FakeCommandStatsStore()

    await handler.show_daily_command_calls(event)

    assert event.replies == [
        "今日指令调用统计：\n统计今日调用：1 次\n总计：1 次"
    ]
    total_call_limit.reset()
