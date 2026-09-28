import logging
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from astrbot_plugin_bqyx.errors import (
    AccountNotConfiguredError,
    ArmyNotBoundError,
    ArmyNotFoundError,
    BotError,
    DuplicateBindingError,
    GameApiError,
    GroupOnlyError,
    ParamError,
    PrivateOnlyError,
    PermissionDeniedError,
    UserNotBoundError,
    UserNotFoundError,
    to_bot_error,
)
from astrbot_plugin_bqyx.hooks import error_reply, format_error_markdown
from bqyx_api.types.erros import BqyxError, UnionNotFoundError, UserNotFoundError as ApiUserNotFoundError


def test_bot_error_formatting():
    err = BotError(
        message="请输入军队ID",
        usage="/绑定军队 <军队ID>",
        extra="例如：/绑定军队 26490",
    )
    md = err.format_markdown()
    assert md.startswith("> ⚠️ **请输入军队ID**")
    assert "**用法**：/绑定军队 <军队ID>" in md
    assert "例如：/绑定军队 26490" in md
    assert err.format_plain() == str(err)
    assert "请输入军队ID" in str(err)


def test_param_error():
    err = ParamError(
        message="军队ID格式错误：请输入纯数字",
        usage="/绑定军队 <军队ID>",
        extra="例如：/绑定军队 26490",
    )
    assert err.is_expected is True
    md = err.format_markdown()
    assert "军队ID格式错误" in md
    assert "/绑定军队 <军队ID>" in md


def test_army_errors():
    not_bound = ArmyNotBoundError()
    assert not_bound.is_expected is True
    md = not_bound.format_markdown()
    assert "当前群尚未绑定军队" in md
    assert "<qqbot-cmd-input" in md

    not_found = ArmyNotFoundError(army_id=20023)
    assert not_found.is_expected is True
    md_found = not_found.format_markdown()
    assert "未查询到军队 ID 20023 的信息" in md_found
    assert "<qqbot-cmd-input" in md_found


def test_user_errors():
    not_bound = UserNotBoundError()
    assert not_bound.is_expected is True
    md = not_bound.format_markdown()
    assert "尚未在本群绑定游戏角色" in md
    assert "<qqbot-cmd-input" in md

    not_found = UserNotFoundError(name_or_uid="张三")
    assert not_found.is_expected is True
    assert "未查询到「张三」的游戏信息" in not_found.format_markdown()


def test_to_bot_error_mappings():
    # 1. UnionNotFoundError
    api_union_err = UnionNotFoundError(status=20023, message="军队id错误")
    bot_err = to_bot_error(api_union_err, army_id=20023)
    assert isinstance(bot_err, ArmyNotFoundError)
    assert "20023" in bot_err.message
    assert bot_err.is_expected is True

    # 2. UserNotFoundError
    api_user_err = ApiUserNotFoundError(status=40002, message="没有这个用户")
    bot_user_err = to_bot_error(api_user_err, target="李四")
    assert isinstance(bot_user_err, UserNotFoundError)
    assert "李四" in bot_user_err.message
    assert bot_user_err.is_expected is True

    # 3. Status 20023 directly
    custom_status_err = SimpleNamespace(status=20023, message="the union id is error")
    mapped = to_bot_error(custom_status_err, army_id=999)
    assert isinstance(mapped, ArmyNotFoundError)

    # 4. Status 10005 (Unauthorized)
    auth_err = SimpleNamespace(status=10005, message="未登录")
    assert isinstance(to_bot_error(auth_err), AccountNotConfiguredError)

    # 5. Generic BqyxError
    generic_bqyx = BqyxError(status=20008, message="用户已有军队")
    mapped_bqyx = to_bot_error(generic_bqyx)
    assert isinstance(mapped_bqyx, GameApiError)
    assert mapped_bqyx.status == 20008
    assert "已有军队" in mapped_bqyx.message

    # 6. BotError passed directly
    orig = BotError("原有错误")
    assert to_bot_error(orig) is orig

    # 7. Unexpected error
    assert to_bot_error(RuntimeError("未知错误")) is None


class EventForErrorTest:
    def __init__(self):
        self.sent = []

    def plain_result(self, text: str):
        return SimpleNamespace(text=text, use_markdown=lambda b: None)


@pytest.mark.asyncio
async def test_error_reply_expected_error_logs_info_only(caplog):
    event = EventForErrorTest()

    @error_reply
    async def sample_handler(self, event):
        if False:
            yield None
        raise UnionNotFoundError(status=20023, message="军队id错误")

    with caplog.at_level(logging.INFO):
        results = []
        async for item in sample_handler(SimpleNamespace(), event):
            results.append(item)

    assert len(results) == 1
    assert "未查询到该军队信息" in results[0].text
    # 验证日志记录在 INFO，未打印 ERROR 堆栈
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("ArmyNotFoundError" in r.message for r in info_records)
    assert len(error_records) == 0


@pytest.mark.asyncio
async def test_error_reply_unexpected_error_logs_exception(caplog):
    event = EventForErrorTest()

    @error_reply
    async def sample_crash_handler(self, event):
        if False:
            yield None
        raise ZeroDivisionError("division by zero")

    with caplog.at_level(logging.INFO):
        results = []
        async for item in sample_crash_handler(SimpleNamespace(), event):
            results.append(item)

    assert len(results) == 1
    assert "ZeroDivisionError" in results[0].text
    # 验证非预期异常记录在 ERROR，且包含堆栈信息
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) > 0
    assert any("handler error" in r.message for r in error_records)
