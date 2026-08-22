from types import SimpleNamespace

import pytest

from bqyx_bot.errors import BotError
from bqyx_bot.hooks import error_reply


class FakeEvent:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply(self, text: str) -> None:
        self.replies.append(text)


@pytest.mark.asyncio
async def test_error_reply_sends_bot_error():
    event = FakeEvent()

    @error_reply
    async def handler(self, event):
        raise BotError("未绑定")

    await handler(SimpleNamespace(), event)
    assert event.replies == ["未绑定"]


@pytest.mark.asyncio
async def test_error_reply_sends_unexpected_error():
    event = FakeEvent()

    @error_reply
    async def handler(self, event):
        raise RuntimeError("boom")

    await handler(SimpleNamespace(), event)
    assert len(event.replies) == 1
    assert "RuntimeError" in event.replies[0]
    assert "boom" in event.replies[0]
