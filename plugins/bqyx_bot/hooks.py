from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from ncatbot.utils import get_log

from .errors import BotError

LOG = get_log("bqyx_bot.hooks")

F = TypeVar("F", bound=Callable[..., Any])


def _format_error(error: BaseException) -> str:
    if isinstance(error, BotError):
        return str(error)
    detail = str(error).strip() or repr(error)
    return f"操作失败，原因：{type(error).__name__}: {detail}"


def _find_event(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any | None:
    for item in args:
        if callable(getattr(item, "reply", None)):
            return item
    event = kwargs.get("event")
    if event is not None and callable(getattr(event, "reply", None)):
        return event
    return None


def _group_id(event: Any) -> str | None:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        group_id = getattr(getattr(event, "data", None), "group_id", None)
    return str(group_id) if group_id is not None else None


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


def _replace_pending(old: Callable[..., Any], new: Callable[..., Any]) -> None:
    """registrar 先收集原函数，装饰器包一层后要替换 pending 里的引用。"""
    try:
        from ncatbot.core.registry.registrar import _pending_handlers
    except Exception:
        return
    for items in _pending_handlers.values():
        for index, item in enumerate(items):
            if item is old:
                items[index] = new


def error_reply(func: F) -> F:
    """捕获 handler 异常，用 event.reply 回群。"""

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            text = _format_error(exc)
            if not isinstance(exc, BotError):
                LOG.exception("handler error: %s", exc)
            event = _find_event(args, kwargs)
            if event is None:
                LOG.exception("handler error 但找不到 event: %s", exc)
                return None
            try:
                await event.reply(text)
            except Exception:
                LOG.exception("发送错误回复失败")
            return None

    _replace_pending(func, wrapper)
    return wrapper  # type: ignore[return-value]


class GroupRateLimiter:
    """按群滑动窗口限流装饰器。

    第一次超限会回复提示；之后如果还继续发，直接忽略，
    并且刷新冷却窗口，停止提问后才恢复。

    name 用于区分命令：窗口 key 为 ``name:group_id``，
    即使多个命令共用同一个限流器实例，各自计数互不影响。
    """

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
        """返回 True 表示放行，False 表示应跳过 handler。"""
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
                    await event.reply(f"操作太频繁，请 {int(self.period)} 秒后再试。")
                except Exception:
                    LOG.exception("发送限流提示失败")
            return False

        self._warned.discard(key)
        window.append(now)
        return True

    def __call__(self, func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            event = _find_event(args, kwargs)
            if event is not None and not await self._check(event):
                return None
            return await func(*args, **kwargs)

        _replace_pending(func, wrapper)
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
                    await event.reply(
                        f"系统调用太频繁（全局限制 {self.max_calls} RPM），请稍后再试。"
                    )
                except Exception:
                    LOG.exception("发送全局限流提示失败")
            return False

        self._window.append(now)
        return True

    def __call__(self, func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any):
            event = _find_event(args, kwargs)
            if event is not None and not await self._check(event):
                return None
            return await func(*args, **kwargs)

        _replace_pending(func, wrapper)
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
        @wraps(func)
        async def tracked(*args: Any, **kwargs: Any):
            # 记录使用次数
            await _record_command_call(args, command_name)
            return await func(*args, **kwargs)

        _replace_pending(func, tracked)
        globally_limited = total_call_limit(tracked)
        return GroupRateLimiter(max_calls, period, name=command_name)(globally_limited)

    return decorator



# 每条群指令各自按群限流 30 秒 1 次，且共享全局 30 RPM 限流。
# 使用 command_rate_limit(name=...) 指定面向用户的主指令名，
# 以便限流键和每日调用统计按指令分别聚合。
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
