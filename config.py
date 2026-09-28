from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 支持当前插件目录与项目根目录的 .env
_PLUGIN_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _PLUGIN_DIR.parent


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    arch_index: int
    snapshot_retention_days: int = 63
    union_snapshot_retention_days: int = 15


def _positive_int(raw: Any, default: int, name: str) -> int:
    try:
        val = int(raw)
        if val >= 1:
            return val
    except (ValueError, TypeError):
        pass
    return default


def load_settings(config: dict | None = None) -> Settings:
    # 优先加载当前插件目录与上级目录的 .env
    if (_PLUGIN_DIR / ".env").exists():
        load_dotenv(_PLUGIN_DIR / ".env")
    elif (_WORKSPACE_ROOT / ".env").exists():
        load_dotenv(_WORKSPACE_ROOT / ".env")

    cfg = config or {}

    username = str(cfg.get("username") or os.getenv("BQYX_USERNAME", "")).strip()
    password = str(cfg.get("password") or os.getenv("BQYX_PASSWORD", "")).strip()

    raw_index = cfg.get("arch_index")
    if raw_index is None:
        raw_index = os.getenv("BQYX_ARCH_INDEX", "4")
    try:
        arch_index = int(raw_index)
        if not (0 <= arch_index <= 7):
            arch_index = 4
    except (ValueError, TypeError):
        arch_index = 4

    retention_days = _positive_int(
        cfg.get("snapshot_retention_days") or os.getenv("BQYX_SNAPSHOT_RETENTION_DAYS"),
        default=63,
        name="snapshot_retention_days",
    )
    union_retention_days = _positive_int(
        cfg.get("union_snapshot_retention_days")
        or os.getenv("BQYX_UNION_SNAPSHOT_RETENTION_DAYS"),
        default=15,
        name="union_snapshot_retention_days",
    )

    return Settings(
        username=username,
        password=password,
        arch_index=arch_index,
        snapshot_retention_days=retention_days,
        union_snapshot_retention_days=union_retention_days,
    )
