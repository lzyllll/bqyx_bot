from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    arch_index: int
    snapshot_retention_days: int = 3
    union_snapshot_retention_days: int = 15


def _positive_int_env(name: str, default: str) -> int:
    raw = os.getenv(name, default).strip() or default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正整数") from exc
    if value < 1:
        raise ValueError(f"{name} 必须是正整数")
    return value


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    username = os.getenv("BQYX_USERNAME", "").strip()
    password = os.getenv("BQYX_PASSWORD", "").strip()
    raw_index = os.getenv("BQYX_ARCH_INDEX", "4").strip() or "4"
    try:
        arch_index = int(raw_index)
    except ValueError as exc:
        raise ValueError("BQYX_ARCH_INDEX 必须是 0-7 的整数") from exc
    if not 0 <= arch_index <= 7:
        raise ValueError("BQYX_ARCH_INDEX 必须是 0-7 的整数")
    return Settings(
        username=username,
        password=password,
        arch_index=arch_index,
        snapshot_retention_days=_positive_int_env("BQYX_SNAPSHOT_RETENTION_DAYS", "3"),
        union_snapshot_retention_days=_positive_int_env(
            "BQYX_UNION_SNAPSHOT_RETENTION_DAYS",
            "15",
        ),
    )
