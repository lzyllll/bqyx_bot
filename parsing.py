from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from astrbot.api.message_components import At

FORMATS = ("图片", "表格", "文本")
_UID_RE = re.compile(r"(\d+)(?:_\d+)?")  # 纯数字，或 数字_数字（UID_存档），提取数字部分


class TargetAt:
    """包装被 @ 或指定的目标 QQ 用户，提供 .user_id 属性。"""

    def __init__(self, user_id: str | int) -> None:
        self.user_id = str(user_id)

    def __str__(self) -> str:
        return self.user_id

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TargetAt):
            return self.user_id == other.user_id
        if hasattr(other, "user_id"):
            return self.user_id == str(getattr(other, "user_id"))
        return self.user_id == str(other)


def extract_uid(text: str) -> str | None:
    match = _UID_RE.search(text or "")
    return match.group(1) if match else None  # 返回下划线前的数字


def extract_command_arg(
    arg: str = "",
    event: Any = None,
    prefixes: tuple[str, ...] = (),
) -> str:
    """从参数或消息文本中提取指令参数，支持自动去除前缀指令名。

    优先使用已绑定的 arg 参数，若为空则从 event.message_str 中匹配并剔除 prefix。
    """
    clean_arg = (arg or "").strip()
    if clean_arg:
        return clean_arg

    if event is not None:
        raw_text = getattr(event, "message_str", "") or ""
        if not raw_text:
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
    for prefix in ("#", "/", "第", "选择", "绑定"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):].strip()
    for suffix in ("号", "个"):
        if raw.endswith(suffix):
            raw = raw[:-len(suffix)].strip()
    try:
        val = int(raw)
        if min_count <= val <= max_count:
            return val
    except (ValueError, TypeError):
        pass
    return None


def _extract_bot_ids(event: Any) -> set[str]:
    """提取机器人自身的账号 ID（QQ 号、OpenID、BotID 等），用于过滤唤醒 @。"""
    bot_ids: set[str] = {
        "qq_official",
        "unknown_selfid",
        "bot",
    }
    # 1. 尝试从 event.get_self_id() 获取
    if hasattr(event, "get_self_id") and callable(event.get_self_id):
        try:
            sid = event.get_self_id()
            if sid is not None and str(sid).strip():
                bot_ids.add(str(sid).strip())
        except Exception:
            pass

    # 2. 从 message_obj.self_id 获取
    msg_obj = getattr(event, "message_obj", None)
    if msg_obj is not None:
        sid = getattr(msg_obj, "self_id", None)
        if sid is not None and str(sid).strip():
            bot_ids.add(str(sid).strip())

        # 针对 qqofficial 的 GroupMessage / C2CMessage
        raw_msg = getattr(msg_obj, "raw_message", None)
        if raw_msg is not None:
            mentions = getattr(raw_msg, "mentions", None)
            if isinstance(mentions, list):
                for m in mentions:
                    mid = getattr(m, "id", None)
                    if mid is not None and str(mid).strip():
                        if getattr(m, "is_you", False) or getattr(m, "bot", False):
                            bot_ids.add(str(mid).strip())
                            m_username = getattr(m, "username", None)
                            if m_username:
                                bot_ids.add(str(m_username).strip())

    # 3. 从 event.bot 获取（botClient / adapter）
    bot = getattr(event, "bot", None)
    if bot is not None:
        for attr in ("self_id", "user_id", "uin", "bot_id"):
            sid = getattr(bot, attr, None)
            if sid is not None and str(sid).strip():
                bot_ids.add(str(sid).strip())
        # qqofficial Client.platform.appid
        platform = getattr(bot, "platform", None)
        if platform is not None:
            appid = getattr(platform, "appid", None)
            if appid is not None and str(appid).strip():
                bot_ids.add(str(appid).strip())

    # 4. 从 event 顶层属性获取
    for attr in ("self_id", "bot_id"):
        sid = getattr(event, attr, None)
        if sid is not None and str(sid).strip():
            bot_ids.add(str(sid).strip())

    # 5. 群聊唤醒 At 兜底：在群聊中，若首个消息段为 At，必定是 @机器人 唤醒指令
    is_private = False
    if hasattr(event, "is_private_chat") and callable(event.is_private_chat):
        try:
            is_private = event.is_private_chat()
        except Exception:
            pass
    if not is_private:
        messages = None
        if hasattr(event, "get_messages") and callable(event.get_messages):
            try:
                messages = event.get_messages()
            except Exception:
                pass
        if not messages and msg_obj is not None:
            messages = getattr(msg_obj, "message", None)
        if messages and isinstance(messages, (list, tuple)) and len(messages) > 0:
            first = messages[0]
            if isinstance(first, At) or getattr(first, "type", None) == "at":
                wake_qq = getattr(first, "qq", None)
                if wake_qq is None and hasattr(first, "data") and isinstance(first.data, dict):
                    wake_qq = first.data.get("qq")
                if wake_qq is not None and str(wake_qq).strip() and str(wake_qq).lower() != "all":
                    bot_ids.add(str(wake_qq).strip())

    bot_ids.discard("")
    return bot_ids


def extract_at(event: Any, target: Any = None) -> TargetAt | None:
    """从群消息事件中提取被 @ 的目标用户，自动过滤唤醒机器人的 @。"""
    bot_ids = _extract_bot_ids(event)

    def _clean_qq(val: Any) -> str | None:
        if val is None:
            return None
        s = str(val).strip().lstrip("@")
        if not s:
            return None
        if s.lower() in ("all", "全体成员"):
            return None
        if s in bot_ids or s.lower() in bot_ids:
            return None
        # 排除常见非用户参数（格式名、相对时间词等）
        if s in ("图片", "表格", "文本", "上月", "上个月", "本月"):
            return None
        # 排除 2026-09、2026/09 等年月参数
        if re.fullmatch(r"\d{4}[-/年\.]\d{1,2}", s):
            return None
        # 排除形如 202609 的 6 位数字年月参数
        if re.fullmatch(r"\d{4}(0[1-9]|1[0-2])", s):
            return None
        # 排除形如 9月、09月 的月份参数
        if re.fullmatch(r"(0?[1-9]|1[0-2])月", s):
            return None
        # 必须是纯数字 QQ 号或合法的用户 openid (长度>=5，且不含非法符号)
        if s.isdigit():
            return s
        if re.fullmatch(r"[a-zA-Z0-9_\-]{5,}", s):
            return s
        return None

    # 1. 优先检查显式传入的 target
    if target is not None:
        if isinstance(target, TargetAt):
            if target.user_id not in bot_ids and target.user_id.lower() not in bot_ids:
                return target
            return None
        if hasattr(target, "user_id") or hasattr(target, "qq"):
            val = getattr(target, "user_id", None) or getattr(target, "qq", None)
            cleaned = _clean_qq(val)
            if cleaned:
                return TargetAt(cleaned)
        else:
            t_raw = str(target).strip()
            if t_raw:
                cleaned = _clean_qq(t_raw)
                if cleaned:
                    return TargetAt(cleaned)

    # 2. 从消息组件列表提取（过滤 bot_ids）
    if hasattr(event, "get_messages") and callable(event.get_messages):
        try:
            for seg in event.get_messages():
                if isinstance(seg, At) or getattr(seg, "type", None) == "at":
                    qq = getattr(seg, "qq", None)
                    if qq is None and hasattr(seg, "data") and isinstance(seg.data, dict):
                        qq = seg.data.get("qq")
                    cleaned = _clean_qq(qq)
                    if cleaned:
                        return TargetAt(cleaned)
        except Exception:
            pass

    # 3. 从兼容结构 message_obj.message 提取
    message = getattr(event, "message", None)
    if not message and hasattr(event, "message_obj"):
        message = getattr(event.message_obj, "message", None)
    if message and isinstance(message, (list, tuple)):
        for seg in message:
            qq = getattr(seg, "user_id", None) or getattr(seg, "qq", None)
            if isinstance(seg, dict):
                qq = seg.get("user_id") or seg.get("qq")
                if not qq and isinstance(seg.get("data"), dict):
                    qq = seg.get("data", {}).get("qq")
            cleaned = _clean_qq(qq)
            if cleaned:
                return TargetAt(cleaned)

    # 4. 从消息文本中正则提取 CQ 码与 @文本（过滤 bot_ids）
    raw_text = getattr(event, "message_str", "") or ""
    for qq in re.findall(r"\[CQ:at,qq=([a-zA-Z0-9_\-]+)\]", raw_text):
        cleaned = _clean_qq(qq)
        if cleaned:
            return TargetAt(cleaned)

    for qq in re.findall(r"@([a-zA-Z0-9_\-]+)", raw_text):
        cleaned = _clean_qq(qq)
        if cleaned:
            return TargetAt(cleaned)

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


def extract_name_and_month(
    text: str = "",
    *,
    default_now: datetime | None = None,
) -> tuple[str, int, int]:
    """从消息参数中分离角色名与目标年月。

    返回: (target_name, year, month)
    若未指定角色名，target_name 为空字符串；
    若未指定年月，则默认返回当前年月。
    """
    from .schedule import as_shanghai

    now = default_now or as_shanghai()
    raw = (text or "").strip()
    if not raw:
        return "", now.year, now.month

    tokens = raw.split()
    date_token = None
    name_tokens = []

    date_patterns = [
        re.compile(r"^\d{4}[-/年\.]\d{1,2}(?:月)?$"),
        re.compile(r"^\d{6}$"),
        re.compile(r"^(?:0?[1-9]|1[0-2])月$"),
    ]

    for t in tokens:
        if date_token is None and (
            t in ("上月", "上个月") or any(p.match(t) for p in date_patterns)
        ):
            date_token = t
        else:
            name_tokens.append(t)

    target_name = " ".join(name_tokens).strip()
    if date_token:
        year, month = parse_year_month(date_token, default_now=now)
    else:
        year, month = now.year, now.month

    return target_name, year, month


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
