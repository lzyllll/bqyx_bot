from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from astrbot.api.event import AstrMessageEvent, MessageChain
from .errors import BotError, bqyx_error_to_bot_error

LOG = logging.getLogger("astrbot_plugin_bqyx.hooks")

F = TypeVar("F", bound=Callable[..., Any])


def _format_error(error: BaseException) -> str:
    bot_err = bqyx_error_to_bot_error(error) or (error if isinstance(error, BotError) else None)
    if bot_err is not None:
        return str(bot_err)
    detail = str(error).strip() or repr(error)
    return f"操作失败，原因：{type(error).__name__}: {detail}"


def _find_event(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any | None:
    for item in args:
        if (
            isinstance(item, AstrMessageEvent)
            or callable(getattr(item, "send", None))
            or callable(getattr(item, "reply", None))
            or callable(getattr(item, "plain_result", None))
            or callable(getattr(item, "make_result", None))
        ):
            return item
    event = kwargs.get("event")
    if event is not None and (
        isinstance(event, AstrMessageEvent)
        or callable(getattr(event, "send", None))
        or callable(getattr(event, "reply", None))
        or callable(getattr(event, "plain_result", None))
        or callable(getattr(event, "make_result", None))
    ):
        return event
    return None


def _group_id(event: Any) -> str | None:
    if hasattr(event, "get_group_id") and callable(event.get_group_id):
        gid = event.get_group_id()
        if gid is not None:
            return str(gid)
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        group_id = getattr(getattr(event, "data", None), "group_id", None)
    return str(group_id) if group_id is not None else None


async def _send_reply(event: Any, text: str) -> None:
    if hasattr(event, "send") and callable(event.send):
        await event.send(MessageChain().message(text))
    elif hasattr(event, "reply") and callable(event.reply):
        await event.reply(text)


async def _record_command_call(args: tuple[Any, ...], command_name: str) -> None:
    """将已放行的命令调用持久化；统计异常不能影响命令本身。"""
    if not args:
        return
    record_call = getattr(getattr(args[0], "store", None), "record_command_call", None)
    if not callable(record_call):
        return
    try:
        await record_call(command_name)
    except Exception:
        LOG.exception("记录指令调用统计失败: %s", command_name)


import inspect


def format_error_markdown(error: BaseException) -> str:
    """将异常转换为标准 Markdown 格式文本，直接根据参数生成，禁止正则。"""
    bot_err = bqyx_error_to_bot_error(error) or (error if isinstance(error, BotError) else None)
    if bot_err is not None:
        return bot_err.format_markdown()

    detail = str(error).strip() or repr(error)
    lines = [
        "> ⚠️ **操作执行失败**",
        f"> 原因：`{type(error).__name__}`: {detail}",
    ]
    return "\n".join(lines)


_format_error = format_error_markdown


def build_error_result(event: Any, error: BaseException) -> Any:
    """生成带有 use_markdown(True) 的 MessageEventResult / MessageChain。"""
    bot_err = bqyx_error_to_bot_error(error) or (error if isinstance(error, BotError) else None)
    target_err = bot_err if bot_err is not None else error
    md_text = format_error_markdown(target_err)
    if hasattr(event, "make_result"):
        res = event.make_result().message(md_text)
    elif hasattr(event, "plain_result"):
        res = event.plain_result(md_text)
    else:
        res = MessageChain().message(md_text)
    if hasattr(res, "use_markdown"):
        res.use_markdown(True)
    return res


_format_error_result = build_error_result


async def _dispatch_error(event: Any, error: BaseException) -> None:
    """向消息平台发送异常消息。支持优先使用 send 发送 Markdown，退化使用 reply。"""
    res = build_error_result(event, error)
    if hasattr(event, "send") and callable(event.send):
        await event.send(res)
    elif hasattr(event, "reply") and callable(event.reply):
        if isinstance(error, BotError):
            await event.reply(str(error))
        else:
            detail = str(error).strip() or repr(error)
            await event.reply(f"操作失败，原因：{type(error).__name__}: {detail}")


def error_reply(func: F) -> F:
    """捕获 handler 异常，回复给群（同时支持普通协程与异步生成器）。"""

    if inspect.isasyncgenfunction(func):
        @wraps(func)
        async def gen_wrapper(*args: Any, **kwargs: Any):
            try:
                async for item in func(*args, **kwargs):
                    yield item
            except Exception as exc:
                bot_err = bqyx_error_to_bot_error(exc) or (exc if isinstance(exc, BotError) else None)
                if bot_err is not None and getattr(bot_err, "is_expected", True):
                    LOG.info("用户指令/业务提示 [%s]: %s", type(bot_err).__name__, bot_err.message)
                else:
                    LOG.exception("handler error: %s", exc)
                event = _find_event(args, kwargs)
                if event is not None:
                    target_err = bot_err if bot_err is not None else exc
                    if hasattr(event, "make_result") or hasattr(event, "plain_result"):
                        yield build_error_result(event, target_err)
                    else:
                        try:
                            await _dispatch_error(event, target_err)
                        except Exception:
                            LOG.exception("发送错误回复失败")

        return gen_wrapper  # type: ignore[return-value]

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            bot_err = bqyx_error_to_bot_error(exc) or (exc if isinstance(exc, BotError) else None)
            if bot_err is not None and getattr(bot_err, "is_expected", True):
                LOG.info("用户指令/业务提示 [%s]: %s", type(bot_err).__name__, bot_err.message)
            else:
                LOG.exception("handler error: %s", exc)
            event = _find_event(args, kwargs)
            if event is None:
                LOG.exception("handler error 但找不到 event: %s", exc)
                return None
            target_err = bot_err if bot_err is not None else exc
            try:
                await _dispatch_error(event, target_err)
            except Exception:
                LOG.exception("发送错误回复失败")
            return None

    return wrapper  # type: ignore[return-value]


class GroupRateLimiter:
    """按群滑动窗口限流装饰器。"""

    def __init__(self, max_calls: int, period: float, name: str = "") -> None:
        self.max_calls = max_calls
        self.period = period
        self.name = name
        self._windows: dict[str, deque[float]] = {}
        self._warned: set[str] = set()

    def _key(self, event: Any) -> str | None:
        group_id = _group_id(event)
        if group_id is None:
            return None
        return f"{self.name}:{group_id}" if self.name else group_id

    def _trim(self, key: str, now: float) -> deque[float]:
        window = self._windows.setdefault(key, deque())
        cutoff = now - self.period
        while window and window[0] <= cutoff:
            window.popleft()
        if not window:
            self._warned.discard(key)
        return window

    async def _check(self, event: Any) -> bool:
        key = self._key(event)
        if key is None:
            return True

        now = time.monotonic()
        window = self._trim(key, now)
        if len(window) >= self.max_calls:
            window.append(now)
            while len(window) > self.max_calls:
                window.popleft()
            if key not in self._warned:
                self._warned.add(key)
                try:
                    await _send_reply(event, f"操作太频繁，请 {int(self.period)} 秒后再试。")
                except Exception:
                    LOG.exception("发送限流提示失败")
            return False

        self._warned.discard(key)
        window.append(now)
        return True

    def __call__(self, func: F) -> F:
        if inspect.isasyncgenfunction(func):
            @wraps(func)
            async def gen_wrapper(*args: Any, **kwargs: Any):
                event = _find_event(args, kwargs)
                if event is not None and not await self._check(event):
                    return
                async for item in func(*args, **kwargs):
                    yield item

            return gen_wrapper  # type: ignore[return-value]

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            event = _find_event(args, kwargs)
            if event is not None and not await self._check(event):
                return None
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]


class GlobalRateLimiter:
    """所有群指令共用的滑动窗口限流器。"""

    def __init__(self, max_calls: int, period: float) -> None:
        self.max_calls = max_calls
        self.period = period
        self._window: deque[float] = deque()
        self._warned_groups: set[str] = set()

    def _trim(self, now: float) -> None:
        cutoff = now - self.period
        while self._window and self._window[0] <= cutoff:
            self._window.popleft()
        if len(self._window) < self.max_calls:
            self._warned_groups.clear()

    def calls_in_period(self) -> int:
        """返回当前滑动窗口内已经放行的调用数。"""
        self._trim(time.monotonic())
        return len(self._window)

    def reset(self) -> None:
        """清空状态，供测试或插件重载时使用。"""
        self._window.clear()
        self._warned_groups.clear()

    async def _check(self, event: Any) -> bool:
        now = time.monotonic()
        self._trim(now)
        if len(self._window) >= self.max_calls:
            group_key = _group_id(event) or "global"
            if group_key not in self._warned_groups:
                self._warned_groups.add(group_key)
                try:
                    await _send_reply(
                        event,
                        f"系统调用太频繁（全局限制 {self.max_calls} RPM），请稍后再试。",
                    )
                except Exception:
                    LOG.exception("发送全局限流提示失败")
            return False

        self._window.append(now)
        return True

    def __call__(self, func: F) -> F:
        if inspect.isasyncgenfunction(func):
            @wraps(func)
            async def gen_wrapper(*args: Any, **kwargs: Any):
                event = _find_event(args, kwargs)
                if event is not None and not await self._check(event):
                    return
                async for item in func(*args, **kwargs):
                    yield item

            return gen_wrapper  # type: ignore[return-value]

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            event = _find_event(args, kwargs)
            if event is not None and not await self._check(event):
                return None
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]


TOTAL_CALLS_PER_MINUTE = 30
DEFAULT_COMMAND_MAX_CALLS = 2
DEFAULT_COMMAND_PERIOD = 30
MY_INFO_COMMAND_PERIOD = 5
total_call_limit = GlobalRateLimiter(max_calls=TOTAL_CALLS_PER_MINUTE, period=60)


def command_rate_limit(
    max_calls: int = DEFAULT_COMMAND_MAX_CALLS,
    period: float = DEFAULT_COMMAND_PERIOD,
    *,
    name: str = "",
) -> Callable[[F], F]:
    """为单条群指令叠加按群及全局两个限流窗口。"""

    def decorator(func: F) -> F:
        command_name = name or func.__qualname__

        if inspect.isasyncgenfunction(func):
            @wraps(func)
            async def tracked_gen(*args: Any, **kwargs: Any):
                await _record_command_call(args, command_name)
                async for item in func(*args, **kwargs):
                    yield item

            globally_limited = total_call_limit(tracked_gen)
            return GroupRateLimiter(max_calls, period, name=command_name)(globally_limited)

        @wraps(func)
        async def tracked(*args: Any, **kwargs: Any):
            await _record_command_call(args, command_name)
            return await func(*args, **kwargs)

        globally_limited = total_call_limit(tracked)
        return GroupRateLimiter(max_calls, period, name=command_name)(globally_limited)

    return decorator


my_info_limit = command_rate_limit(
    max_calls=DEFAULT_COMMAND_MAX_CALLS,
    period=MY_INFO_COMMAND_PERIOD,
    name="我的信息",
)
rpm_check_limit = command_rate_limit(name="统计RPM")
daily_call_stats_limit = command_rate_limit(name="统计今日调用")
auto_bind_limit = command_rate_limit(name="一键绑定")
union_live_limit = command_rate_limit(name="今日日贡排行")
yesterday_union_limit = command_rate_limit(name="昨日日贡排行")
total_union_limit = command_rate_limit(name="实时军队排行")
this_week_union_limit = command_rate_limit(name="本周周贡排行")
last_week_union_limit = command_rate_limit(name="上周周贡排行")
my_dps_limit = command_rate_limit(
    max_calls=3,
    period=60,
    name="我的战力",
)
