from __future__ import annotations

import re
from datetime import datetime
from typing import Any

FORMATS = ("图片", "表格", "文本")
_UID_RE = re.compile(r"(\d+)(?:_\d+)?")  # 纯数字，或 数字_数字（UID_存档），提取数字部分


def extract_uid(text: str) -> str | None:
    match = _UID_RE.search(text or "")
    return match.group(1) if match else None  # 返回下划线前的数字


def extract_command_arg(
    arg: str = "",
    event: Any = None,
    prefixes: tuple[str, ...] = (),
) -> str:
    """从参数或消息文本中提取指令参数，支持自动去除前缀指令名。

    优先使用已绑定的 arg 参数，若为空则从 event.message.text 中匹配并剔除 prefix。
    """
    clean_arg = (arg or "").strip()
    if clean_arg:
        return clean_arg

    if event is not None:
        message = getattr(event, "message", None)
        raw_text = getattr(message, "text", "") or ""
        text = raw_text.strip()
        for prefix in prefixes:
            if text.startswith(prefix):
                return text[len(prefix) :].strip()

    return ""


def parse_choice_index(
    text: str | None,
    max_count: int,
    min_count: int = 1,
) -> int | None:
    """解析会话选择回复中的序号，仅在 [min_count, max_count] 范围时返回有效整数，否则返回 None。"""
    if text is None:
        return None
    raw = str(text).strip()
    try:
        val = int(raw)
        if min_count <= val <= max_count:
            return val
    except (ValueError, TypeError):
        pass
    return None


def extract_at(event: Any, target: Any = None) -> Any | None:
    """从群消息事件中提取被 @ 的用户（At 消息段）。"""
    if target is not None:
        return target

    message = getattr(event, "message", None)
    if message:
        try:
            from ncatbot.types import At

            for seg in message:
                if isinstance(seg, At):
                    return seg
        except (TypeError, ImportError):
            pass
    return None


def parse_year_month(
    text: str = "",
    *,
    default_now: datetime | None = None,
) -> tuple[int, int]:
    """从消息文本中解析目标年月（支持 2026-09、2026/09、202609、上月 等）。"""
    from .schedule import as_shanghai

    now = default_now or as_shanghai()
    year, month = now.year, now.month

    raw = (text or "").strip()
    if "上月" in raw or "上个月" in raw:
        if month == 1:
            return year - 1, 12
        return year, month - 1

    m = re.search(r"(\d{4})[-/年\.](\d{1,2})", raw)
    if m:
        return int(m.group(1)), int(m.group(2))

    m2 = re.search(r"\b(\d{4})(0[1-9]|1[0-2])\b", raw)
    if m2:
        return int(m2.group(1)), int(m2.group(2))

    m3 = re.search(r"(?:^|[^\d])(0?[1-9]|1[0-2])月", raw)
    if m3:
        return year, int(m3.group(1))

    return year, month


def parse_format_and_limit(
    text: str,
    *,
    default_limit: int | None = None,
    default_format: str = "图片",
) -> tuple[int | None, str]:
    tokens = text.split()[1:]
    limit = default_limit
    fmt = default_format
    for token in tokens:
        if token in FORMATS:
            fmt = token
            continue
        try:
            limit = int(token)
        except ValueError:
            continue
    return limit, fmt


def parse_format(text: str, default: str = "图片") -> str:
    _, fmt = parse_format_and_limit(text, default_format=default)
    return fmt
