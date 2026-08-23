from types import SimpleNamespace

import pytest

from bqyx_bot.hooks import GroupRateLimiter


class FakeEvent:
    def __init__(self, group_id: str = "100") -> None:
        self.group_id = group_id
        self.replies: list[str] = []

    async def reply(self, text: str) -> None:
        self.replies.append(text)


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
