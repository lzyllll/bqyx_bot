from __future__ import annotations

import re

FORMATS = ("图片", "表格", "文本")
_UID_RE = re.compile(r"(\d+)(?:_\d+)?")  # 纯数字，或 数字_数字（UID_存档），提取数字部分

def extract_uid(text: str) -> str | None:
    match = _UID_RE.search(text or "")
    return match.group(1) if match else None  # 返回下划线前的数字

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
