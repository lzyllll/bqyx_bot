from types import SimpleNamespace

import pytest
from bqyx_bot.handlers.help import HelpHandlers
from bqyx_bot.hooks import GroupRateLimiter, command_rate_limit, total_call_limit


class FakeEvent:
    def __init__(self, group_id: str = "100") -> None:
        self.group_id = group_id
        self.replies: list[str] = []

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

    assert await handler(SimpleNamespace(), event) == "ok"
    assert event.replies == []

    assert await handler(SimpleNamespace(), event) is None
    assert len(event.replies) == 1
    assert "操作太频繁" in event.replies[0]

    assert await handler(SimpleNamespace(), event) is None
    assert len(event.replies) == 1


@pytest.mark.asyncio
async def test_rate_limit_keeps_blocking_while_still_asking(monkeypatch):
    limiter = GroupRateLimiter(max_calls=1, period=10)
    event = FakeEvent()
    clock = {"now": 100.0}
    monkeypatch.setattr("bqyx_bot.hooks.time.monotonic", lambda: clock["now"])

    @limiter
    async def handler(self, event):
        return "ok"

    assert await handler(SimpleNamespace(), event) == "ok"

    clock["now"] = 100.1
    assert await handler(SimpleNamespace(), event) is None

    clock["now"] = 109.0
    assert await handler(SimpleNamespace(), event) is None

    clock["now"] = 109.5
    assert await handler(SimpleNamespace(), event) is None
    assert len(event.replies) == 1


def test_rate_limiter_name_prefixes_key():
    limiter = GroupRateLimiter(max_calls=1, period=60, name="今日日贡")
    assert limiter._key(FakeEvent("100")) == "今日日贡:100"
    # 无 name 时兼容原行为：key 就是群 ID
    plain = GroupRateLimiter(max_calls=1, period=60)
    assert plain._key(FakeEvent("100")) == "100"
    # 无群 ID 时返回 None（不限流）
    assert limiter._key(FakeEvent(group_id=None)) is None


@pytest.mark.asyncio
async def test_command_limits_are_per_command_and_share_global_rpm(monkeypatch):
    """RL-04: 默认命令按群每 30 秒 1 次，放行调用共享全局 RPM 窗口。"""
    total_call_limit.reset()
    monkeypatch.setattr("bqyx_bot.hooks.time.monotonic", lambda: 100.0)

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

    # 同一群重复第一条命令被拦截，但另一条命令拥有独立的群窗口。
    assert await first_handler(SimpleNamespace(), first_event) is None
    assert first_event.replies == ["操作太频繁，请 30 秒后再试。"]
    assert total_call_limit.calls_in_period() == 2

    total_call_limit.reset()


@pytest.mark.asyncio
async def test_command_rate_limit_supports_the_five_second_my_info_exception(
    monkeypatch,
):
    """RL-07: 我的信息可使用 5 秒 1 次的独立群限流窗口。"""
    total_call_limit.reset()
    clock = {"now": 100.0}
    monkeypatch.setattr("bqyx_bot.hooks.time.monotonic", lambda: clock["now"])
    event = FakeEvent()

    @command_rate_limit(max_calls=1, period=5, name="我的信息")
    async def my_info_handler(self, event):
        return "ok"

    assert await my_info_handler(SimpleNamespace(), event) == "ok"
    clock["now"] = 104.9
    assert await my_info_handler(SimpleNamespace(), event) is None
    # 超限尝试会延长冷却窗口；停止调用满 5 秒后恢复。
    clock["now"] = 109.9
    assert await my_info_handler(SimpleNamespace(), event) == "ok"
    total_call_limit.reset()


@pytest.mark.asyncio
async def test_global_rpm_limit_warns_each_group_once(monkeypatch):
    """RL-05: 全局 RPM 满载时阻止所有命令，并向受影响的群提示一次。"""
    total_call_limit.reset()
    monkeypatch.setattr(total_call_limit, "max_calls", 1)
    monkeypatch.setattr("bqyx_bot.hooks.time.monotonic", lambda: 100.0)

    first_event = FakeEvent("100")
    second_event = FakeEvent("200")

    @command_rate_limit(max_calls=5, period=60)
    async def handler(self, event):
        return "ok"

    assert await handler(SimpleNamespace(), first_event) == "ok"
    assert await handler(SimpleNamespace(), second_event) is None
    assert second_event.replies == ["系统调用太频繁（全局限制 1 RPM），请稍后再试。"]
    assert total_call_limit.calls_in_period() == 1

    total_call_limit.reset()


@pytest.mark.asyncio
async def test_rpm_command_reports_the_current_global_window(monkeypatch):
    """RL-06: 统计RPM 命令显示包含自身在内的当前全局调用次数。"""
    total_call_limit.reset()
    monkeypatch.setattr("bqyx_bot.hooks.time.monotonic", lambda: 100.0)
    event = FakeEvent()

    await HelpHandlers().show_rpm(event)

    assert event.replies == ["当前全局 RPM：1/30"]
    total_call_limit.reset()


@pytest.mark.asyncio
async def test_command_stats_record_only_calls_that_pass_both_limits(monkeypatch):
    """DS-01: 每日统计只记录通过群级和全局限流的指令调用。"""
    total_call_limit.reset()
    monkeypatch.setattr("bqyx_bot.hooks.time.monotonic", lambda: 100.0)
    event = FakeEvent()
    store = FakeCommandStatsStore()

    @command_rate_limit(name="测试指令")
    async def handler(self, event):
        return "ok"

    plugin = SimpleNamespace(store=store)
    assert await handler(plugin, event) == "ok"
    assert await handler(plugin, event) is None
    assert store.counts == {"测试指令": 1}
    total_call_limit.reset()


@pytest.mark.asyncio
async def test_daily_command_stats_include_the_stats_command(monkeypatch):
    """DS-02: 统计今日调用的输出按次数展示，并包含该统计命令自身。"""
    total_call_limit.reset()
    monkeypatch.setattr("bqyx_bot.hooks.time.monotonic", lambda: 100.0)
    event = FakeEvent()
    handler = HelpHandlers()
    handler.store = FakeCommandStatsStore()

    await handler.show_daily_command_calls(event)

    assert event.replies == [
        "今日指令调用统计：\n统计今日调用：1 次\n总计：1 次"
    ]
    total_call_limit.reset()
