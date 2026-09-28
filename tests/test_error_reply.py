from types import SimpleNamespace

import pytest

from astrbot_plugin_bqyx.errors import BotError
from astrbot_plugin_bqyx.hooks import error_reply


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


@pytest.mark.asyncio
async def test_filter_command_on_top_catches_bot_error_in_call_handler():
    import functools
    from unittest.mock import MagicMock
    from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
    from astrbot.core.pipeline.context_utils import call_handler
    from astrbot_plugin_bqyx.errors import ParamError

    class SampleHandler:
        @filter.command("test_error_cmd")
        @error_reply
        async def my_cmd(self, event: AstrMessageEvent, name: str = ""):
            raise ParamError("请输入角色名", usage="/test_error_cmd <角色名>")
            yield None

    reg = filter.command.__globals__["star_handlers_registry"]
    target_meta = next(h for h in reg if h.handler_name == "my_cmd")

    mock_event = MagicMock(spec=AstrMessageEvent)
    mock_event.make_result.return_value = MessageEventResult()

    bound_fn = functools.partial(target_meta.handler, SampleHandler())
    wrapper = call_handler(mock_event, bound_fn)

    results = []
    async for r in wrapper:
        results.append(r)

    # 验证异常已被 @error_reply 截获并正常 yield，绝不会冒泡抛给 AstrBot core
    assert len(results) == 1
    assert mock_event.set_result.called
    sent_result = mock_event.set_result.call_args[0][0]
    plain_text = "".join(getattr(c, "text", "") for c in getattr(sent_result, "chain", []))
    assert "请输入角色名" in plain_text
