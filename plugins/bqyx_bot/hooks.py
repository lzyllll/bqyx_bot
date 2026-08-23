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


query_limit = GroupRateLimiter(max_calls=15, period=60)
auto_bind_limit = GroupRateLimiter(max_calls=3, period=60)
# 军队排行：实时查询（今日日贡）2 次/分；快照查询（昨日日贡/军队排行）各 6 次/分
union_live_limit = GroupRateLimiter(max_calls=2, period=60, name="今日日贡")
yesterday_union_limit = GroupRateLimiter(max_calls=6, period=60, name="昨日日贡")
total_union_limit = GroupRateLimiter(max_calls=6, period=60, name="军队排行")
