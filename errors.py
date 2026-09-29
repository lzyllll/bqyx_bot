from __future__ import annotations

import logging
from typing import Any

from .reply import md_cmd_example, md_cmd_input

LOG = logging.getLogger("astrbot_plugin_bqyx.errors")


class BotError(Exception):
    """可直接回复给用户的业务与参数异常基类，支持结构化 Markdown 输出。"""

    is_expected: bool = True
    """标记为预期内异常（如参数错误、未绑定、军队不存在等），不应在日志中记录 ERROR 堆栈。"""

    icon: str = "⚠️"
    """展示在 Markdown 引用块前缀的图标，默认为 ⚠️。"""

    def __init__(
        self,
        message: str,
        extra: str = "",
        *,
        usage: str = "",
        icon: str | None = None,
        is_expected: bool = True,
    ) -> None:
        self.message = message
        self.extra = extra
        self.usage = usage
        if icon is not None:
            self.icon = icon
        self.is_expected = is_expected

        full = message
        if usage:
            full += f"\n用法：{usage}"
        if extra:
            full += f"\n{extra}"
        super().__init__(full)

    def format_markdown(self) -> str:
        """直接根据参数生成标准 Markdown 引用块，禁止正则。"""
        lines = [f"> {self.icon} **{self.message}**"]
        if self.usage:
            if "\n" in self.usage:
                lines.append("> \n" + "\n".join(f"> {l}" for l in self.usage.splitlines()))
            else:
                lines.append(f"> **用法**：{self.usage}")
        if self.extra:
            for line in self.extra.splitlines():
                lines.append(f"> {line}")
        return "\n".join(lines)

    def format_plain(self) -> str:
        """生成纯文本提示（用于不支持 Markdown 的降级场景）。"""
        return str(self)


class ParamError(BotError):
    """用户输入参数错误（如缺失参数、非纯数字、格式错误等）。"""

    def __init__(
        self,
        message: str = "参数错误",
        usage: str = "",
        extra: str = "",
        *,
        icon: str = "⚠️",
    ) -> None:
        super().__init__(message=message, usage=usage, extra=extra, icon=icon, is_expected=True)


class GroupOnlyError(BotError):
    """仅群聊可用指令在私聊中使用时触发。"""

    def __init__(self, message: str = "该指令仅支持在群聊中使用。") -> None:
        super().__init__(message=message, is_expected=True)


class PrivateOnlyError(BotError):
    """仅私聊可用指令在群聊中使用时触发。"""

    def __init__(self, message: str = "该指令仅支持在私聊中使用。") -> None:
        super().__init__(message=message, is_expected=True)


class PermissionDeniedError(BotError):
    """权限不足（例如仅群管理员或群主可操作）。"""

    def __init__(self, message: str = "权限不足，仅管理员或群主可执行此操作。") -> None:
        super().__init__(message=message, is_expected=True)


class ArmyNotBoundError(BotError):
    """群未绑定军队。"""

    def __init__(self) -> None:
        tag = md_cmd_input("/绑定军队", "绑定军队")
        ex = md_cmd_example("/绑定军队 1234", "绑定军队 1234")
        super().__init__(
            message="当前群尚未绑定军队",
            usage=f"{tag} `<军队ID>`",
            extra=f"请管理员先使用：{ex}",
            is_expected=True,
        )


class ArmyNotFoundError(BotError):
    """未查询到指定军队（ID错误或军队不存在）。"""

    def __init__(self, army_id: int | str = "") -> None:
        msg = (
            f"未查询到军队 ID {army_id} 的信息，请确认军队ID是否正确。"
            if army_id
            else "未查询到该军队信息，请确认军队ID是否正确。"
        )
        tag = md_cmd_input("/绑定军队", "绑定军队")
        ex = md_cmd_example("/绑定军队 26490", "绑定军队 26490")
        super().__init__(
            message=msg,
            usage=f"{tag} `<军队ID>`",
            extra=f"例如：{ex}",
            is_expected=True,
        )


class UserNotBoundError(BotError):
    """用户未在当前群绑定游戏角色。"""

    def __init__(self) -> None:
        tag_name = md_cmd_input("/绑定游戏名", "绑定游戏名")
        tag_uid = md_cmd_input("/绑定uid", "绑定uid")
        tag_all = md_cmd_example("/绑定游戏名 ~", "绑定游戏名 ~")
        ex_name = md_cmd_example("/绑定游戏名 张三", "绑定游戏名 张三")
        ex_uid = md_cmd_example("/绑定uid 123456", "绑定uid 123456")
        super().__init__(
            message="你尚未在本群绑定游戏角色",
            usage=f"{tag_name} `<角色名>` 或 {tag_all} 或 {tag_uid} `<UID>`",
            extra=f"• 方式1：{ex_name}（推荐，支持模糊匹配）\n• 方式2：{tag_all}（列出全部成员直接点击绑定）\n• 方式3：{ex_uid}",
            is_expected=True,
        )


class UserNotFoundError(BotError):
    """未找到指定游戏用户或角色。"""

    def __init__(self, name_or_uid: str = "") -> None:
        msg = f"未查询到「{name_or_uid}」的游戏信息。" if name_or_uid else "未查询到指定游戏角色的信息。"
        super().__init__(message=msg, is_expected=True)


class AccountNotConfiguredError(BotError):
    """代理账号未配置。"""

    def __init__(self) -> None:
        super().__init__(
            message="代理账号未配置",
            extra="请在 AstrBot 管理面板或 .env 中设置 BQYX_USERNAME 和 BQYX_PASSWORD。",
            is_expected=True,
        )


class GameApiError(BotError):
    """游戏服务端返回的业务错误（如 status=20008 用户已有军队 等）。"""

    def __init__(self, message: str, status: int | None = None, *, extra: str = "") -> None:
        self.status = status
        suffix = f" (错误码: {status})" if status else ""
        super().__init__(message=f"游戏接口提示：{message}{suffix}", extra=extra, is_expected=True)


class DuplicateBindingError(BotError):
    """账号在军队中有多个存档。"""

    def __init__(self, indexes: str = "") -> None:
        msg = f"该账号在本军有多个存档（{indexes}），无法自动绑定。" if indexes else "该账号在本军有多个存档，无法自动绑定。"
        super().__init__(message=msg, is_expected=True)


def bqyx_error_to_bot_error(error: BaseException, **kwargs: Any) -> BotError | None:
    """尝试将第三方/底层 API 的业务异常（例如 bqyx_api 的 UnionNotFoundError 等）转换为结构化 BotError。

    如果已经是 BotError 则直接返回；如果是已知游戏业务错误则转换并赋予友好的提示信息。
    """
    if isinstance(error, BotError):
        return error

    error_name = type(error).__name__

    # 1. 军队不存在或军队ID错误 (如 UnionNotFoundError, 或 status 20023 / 20011)
    status = getattr(error, "status", None) or getattr(error, "id", None)
    if (
        error_name == "UnionNotFoundError"
        or "UnionNotFoundError" in str(type(error))
        or status in (20011, 20023)
    ):
        army_id = kwargs.get("army_id", "")
        return ArmyNotFoundError(army_id=army_id)

    # 2. 用户未找到 (如 UserNotFoundError, 或 status 40002)
    if (
        error_name == "UserNotFoundError"
        or "UserNotFoundError" in str(type(error))
        or status == 40002
    ):
        target = kwargs.get("target") or kwargs.get("name_or_uid", "")
        return UserNotFoundError(name_or_uid=str(target))

    # 3. 登录或未授权错误
    if error_name in ("LoginError", "UnauthorizedError") or status in (10005, 99999):
        return AccountNotConfiguredError()

    # 4. BqyxError 其他通用业务错误（如 status=20008 用户已有军队 等）
    mro_names = [b.__name__ for b in type(error).__mro__]
    if "BqyxError" in mro_names or (status is not None and isinstance(status, int) and status > 0):
        msg = getattr(error, "message", None) or str(error)
        return GameApiError(message=msg, status=status)

    return None


to_bot_error = bqyx_error_to_bot_error
