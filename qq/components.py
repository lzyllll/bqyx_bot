"""QQ 官方平台消息按钮（Keyboard）组件（参照 PR #7868）。

字段集对齐 botpy 的 TypedDict 定义，
发送时产出的 dict 可直接作为 QQ OpenAPI `keyboard` 字段。
"""

from __future__ import annotations

import sys
from typing import Any, ClassVar

import botpy.message
from botpy.http import Route
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.message.components import BaseMessageComponent
if sys.version_info >= (3, 14):
    from pydantic import BaseModel
else:
    from pydantic.v1 import BaseModel


class QQCPermission(BaseModel):
    """按钮可操作权限。

    permission.type:
      0 - 指定用户可操作（需 specify_user_ids）
      1 - 仅管理员可操作
      2 - 所有人可操作
      3 - 指定身份组可操作（需 specify_role_ids）
    """

    type: int = 2
    specify_user_ids: list[str] | None = None
    specify_role_ids: list[str] | None = None

    def to_dict(self) -> dict:
        data: dict = {"type": self.type}
        if self.specify_user_ids is not None:
            data["specify_user_ids"] = self.specify_user_ids
        if self.specify_role_ids is not None:
            data["specify_role_ids"] = self.specify_role_ids
        return data


class QQCButton(BaseMessageComponent):
    """QQ 官方平台按钮组件（对齐 QQ OpenAPI v2 最新规范）。

    action_type (行为类型):
      0 - 跳转（http 网页或小程序，data 为 URL）
      1 - 回调（data 为 callback 交互数据，点击后服务端接收 INTERACTION_CREATE 事件）
      2 - 发送指令（data 为命令文本）

    style (按钮样式):
      0 - 灰色线框（secondary）
      1 - 蓝色线框（primary，默认）
      3 - 白色背景 + 红色字体
      4 - 蓝色背景 + 白色字体
    """

    type: str = "qqc_button"  # type: ignore[assignment]
    id: str = ""
    label: str = ""
    visited_label: str | None = None
    style: int = 1
    action_type: int = 1
    data: str = ""
    reply: bool = False
    enter: bool = False
    unsupport_tips: str | None = None
    permission: QQCPermission | None = None
    group_id: str | None = None

    def __init__(
        self,
        id: str,
        label: str,
        data: str = "",
        visited_label: str | None = None,
        style: int = 1,
        action_type: int = 1,
        reply: bool = False,
        enter: bool = False,
        unsupport_tips: str | None = None,
        permission: QQCPermission | None = None,
        group_id: str | None = None,
    ) -> None:
        super().__init__(
            id=id,
            label=label,
            visited_label=visited_label if visited_label is not None else label,
            style=style,
            action_type=action_type,
            data=data,
            reply=reply,
            enter=enter,
            unsupport_tips=unsupport_tips,
            permission=permission,
            group_id=group_id,
        )

    def to_dict(self) -> dict:  # type: ignore[override]
        render_data = {
            "label": self.label,
            "visited_label": self.visited_label,
            "style": self.style,
        }
        action: dict = {
            "type": self.action_type,
            "data": self.data,
            "permission": (self.permission or QQCPermission(type=2)).to_dict(),
        }
        if self.reply:
            action["reply"] = True
        if self.enter:
            action["enter"] = True
        if self.unsupport_tips is not None:
            action["unsupport_tips"] = self.unsupport_tips
        if self.group_id is not None:
            action["group_id"] = self.group_id
        return {
            "id": self.id,
            "render_data": render_data,
            "action": action,
        }

    @classmethod
    def link(
        cls,
        label: str,
        url: str,
        id: str | None = None,
        visited_label: str | None = None,
        style: int = 1,
        permission: QQCPermission | None = None,
    ) -> QQCButton:
        """快速构造跳转链接按钮 (action_type=0)。"""
        return cls(
            id=id or f"link_{label}",
            label=label,
            data=url,
            action_type=0,
            visited_label=visited_label,
            style=style,
            permission=permission,
        )

    @classmethod
    def command(
        cls,
        label: str,
        cmd: str,
        id: str | None = None,
        enter: bool = True,
        reply: bool = False,
        visited_label: str | None = None,
        style: int = 0,
        permission: QQCPermission | None = None,
    ) -> QQCButton:
        """快速构造自动发送指令按钮 (action_type=2)。"""
        return cls(
            id=id or f"cmd_{label}",
            label=label,
            data=cmd,
            action_type=2,
            enter=enter,
            reply=reply,
            visited_label=visited_label,
            style=style,
            permission=permission,
        )

    @classmethod
    def callback(
        cls,
        label: str,
        data: str,
        id: str | None = None,
        visited_label: str | None = None,
        style: int = 1,
        permission: QQCPermission | None = None,
        group_id: str | None = None,
    ) -> QQCButton:
        """快速构造回调按钮 (action_type=1)。"""
        return cls(
            id=id or f"cb_{label}",
            label=label,
            data=data,
            action_type=1,
            visited_label=visited_label,
            style=style,
            permission=permission,
            group_id=group_id,
        )


class QQCKeyboard(BaseMessageComponent):
    """QQ 官方平台消息按钮（Keyboard）组件（对齐 QQ OpenAPI v2 最新规范）。

    支持：
    1. 自定义按钮布局（rows）：最多 5 行，每行最多 5 个按钮。
    2. 官方报备的模板键盘（id）：例如 `QQCKeyboard(id="1070001")`。
    """

    type: str = "qqc_keyboard"  # type: ignore[assignment]
    id: str | None = None
    rows: list[list[QQCButton]]

    MAX_ROWS: ClassVar[int] = 5
    MAX_BUTTONS_PER_ROW: ClassVar[int] = 5

    def __init__(
        self,
        rows: list[list[QQCButton]] | None = None,
        *,
        id: str | None = None,
    ) -> None:
        rows = rows if rows is not None else []
        if len(rows) > self.MAX_ROWS:
            raise ValueError(f"QQCKeyboard 行数超限：{len(rows)} > {self.MAX_ROWS}")
        for idx, row in enumerate(rows):
            if len(row) > self.MAX_BUTTONS_PER_ROW:
                raise ValueError(
                    f"QQCKeyboard 第 {idx + 1} 行按钮数超限："
                    f"{len(row)} > {self.MAX_BUTTONS_PER_ROW}"
                )
        super().__init__(rows=rows, id=id)

    def add_row(self, *buttons: QQCButton) -> QQCKeyboard:
        """添加一行按钮。"""
        if len(self.rows) >= self.MAX_ROWS:
            raise ValueError(f"QQCKeyboard 行数超限：最多 {self.MAX_ROWS} 行")
        if len(buttons) > self.MAX_BUTTONS_PER_ROW:
            raise ValueError(f"单行按钮数超限：最多 {self.MAX_BUTTONS_PER_ROW} 个")
        self.rows.append(list(buttons))
        return self

    def add_button(self, button: QQCButton, row_index: int = -1) -> QQCKeyboard:
        """向指定行（默认最后一行）追加一个按钮，若当前无行或该行已满则自动新建行。"""
        if not self.rows or len(self.rows[row_index]) >= self.MAX_BUTTONS_PER_ROW:
            if len(self.rows) >= self.MAX_ROWS:
                raise ValueError(f"QQCKeyboard 行数已达到上限 {self.MAX_ROWS}")
            self.rows.append([button])
        else:
            self.rows[row_index].append(button)
        return self

    def to_dict(self) -> dict:  # type: ignore[override]
        if self.id:
            return {"id": self.id}
        return {
            "content": {
                "rows": [
                    {"buttons": [btn.to_dict() for btn in row]} for row in self.rows
                ],
            },
        }

    async def send(
        self,
        event: AstrMessageEvent,
        content: str | dict | None = None,
        *,
        markdown: str | dict | None = None,
        msg_type: int = 2,
        msg_id: str | None = None,
        msg_seq: int = 1,
        is_wakeup: bool = False,
        stop_event: bool = True,
    ) -> Any:
        """快捷方法：发送当前键盘消息至指定的 QQ 官方平台事件。

        - content / markdown: 消息正文（Markdown 格式字符串）。
        - 官方规范中，按钮（Keyboard）需挂载于 Markdown 消息上，故默认 msg_type=2。
        """
        return await send_keyboard(
            event=event,
            content=content,
            keyboard=self,
            markdown=markdown,
            msg_type=msg_type,
            msg_id=msg_id,
            msg_seq=msg_seq,
            is_wakeup=is_wakeup,
            stop_event=stop_event,
        )


async def send_c2c_message(
    event: AstrMessageEvent,
    content: str | dict | None = None,
    *,
    openid: str | None = None,
    keyboard: QQCKeyboard | dict | str | list[list[QQCButton]] | None = None,
    markdown: str | dict | None = None,
    msg_type: int = 2,
    msg_id: str | None = None,
    msg_seq: int = 1,
    is_wakeup: bool = False,
    message_reference: dict | None = None,
    media: dict | None = None,
    stop_event: bool = True,
) -> Any:
    """依照 QQ 官方开放平台规范发送单聊（私聊 C2C）消息。

    接口规范: POST /v2/users/{user_openid}/messages
    官方文档: https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html

    注：QQ 官方已废弃 template_id / custom_template_id / params 模板字段，
    Markdown 消息统一使用原生 content 字段直接传递 Markdown 文本。

    :param event: 当前消息事件
    :param content: 消息正文。当 msg_type=2（默认）时自动包装为 {"content": content}
    :param openid: 目标用户 user_openid（缺省时自动从 event / raw_message 获取）
    :param keyboard: 键盘组件（QQCKeyboard 实例、模板 ID 字符串、按钮二维列表或 dict）
    :param markdown: Markdown 正文（与 content 等效，便于不同调用习惯）
    :param msg_type: 消息类型：0 为纯文本，2 为 Markdown，7 为富媒体（默认 2）
    :param msg_id: 被回复消息的 ID（被动回复 60 分钟内有效，最多回复 4 次）
    :param msg_seq: 回复序号（与 msg_id 结合使用，1-4）
    :param is_wakeup: 是否为互动召回消息（用户主动交互后 30 天内唤醒）
    :param message_reference: 消息引用配置
    :param media: 富媒体文件信息对象
    :param stop_event: 发送后是否终止事件传播（默认 True）
    :return: 平台 API 发送结果
    """
    bot = getattr(event, "bot", None)
    raw_msg = getattr(getattr(event, "message_obj", None), "raw_message", None)

    if bot is None:
        raise TypeError(f"事件 {type(event).__name__} 缺少 bot 对象，请确保在 QQ 官方平台下调用")

    # 1. 解析目标用户 openid
    target_openid = openid
    if not target_openid and raw_msg:
        target_openid = getattr(getattr(raw_msg, "author", None), "user_openid", None) or getattr(raw_msg, "user_openid", None)
    if not target_openid and hasattr(event, "get_sender_id"):
        target_openid = event.get_sender_id()
    if not target_openid:
        raise ValueError("无法获取目标用户的 user_openid")

    # 2. 解析 msg_id
    target_msg_id = (
        msg_id
        or getattr(raw_msg, "id", None)
        or getattr(getattr(event, "message_obj", None), "message_id", None)
    )

    # 3. 解析 keyboard（支持组件、模板ID、按钮列表、dict）
    keyboard_payload: dict | None = None
    if isinstance(keyboard, QQCKeyboard):
        keyboard_payload = keyboard.to_dict()
    elif isinstance(keyboard, str):
        keyboard_payload = {"id": keyboard}
    elif isinstance(keyboard, list):
        keyboard_payload = QQCKeyboard(keyboard).to_dict()
    elif isinstance(keyboard, dict):
        keyboard_payload = keyboard
    elif keyboard is not None:
        raise TypeError(f"不支持的 keyboard 类型: {type(keyboard).__name__}")

    # 4. 解析正文（官方已废弃 template_id，仅支持 content 原生 Markdown）
    markdown_payload: dict | None = None
    text_content: str | None = None

    raw_text = markdown if markdown is not None else content
    if raw_text is not None:
        if isinstance(raw_text, dict):
            markdown_payload = raw_text
            msg_type = 2
        elif msg_type == 2:
            markdown_payload = {"content": str(raw_text)}
        else:
            text_content = str(raw_text)

    # 5. 构建请求体（严格遵循官方 OpenAPI v2 规范）
    payload: dict[str, Any] = {
        "msg_type": msg_type,
    }
    if text_content is not None:
        payload["content"] = text_content
    if markdown_payload is not None:
        payload["markdown"] = markdown_payload
    if keyboard_payload is not None:
        payload["keyboard"] = keyboard_payload
    if media is not None:
        payload["media"] = media
    if message_reference is not None:
        payload["message_reference"] = message_reference
    if target_msg_id:
        payload["msg_id"] = target_msg_id
        payload["msg_seq"] = msg_seq
    if is_wakeup:
        payload["is_wakeup"] = True

    # 6. 发送 HTTP 请求
    ret = None
    try:
        route = Route("POST", "/v2/users/{openid}/messages", openid=target_openid)
        if hasattr(bot, "api") and hasattr(bot.api, "_http") and hasattr(bot.api._http, "request"):
            ret = await bot.api._http.request(route, json=payload)
        elif hasattr(event, "post_c2c_message"):
            ret = await event.post_c2c_message(**payload)
        elif hasattr(bot, "api") and hasattr(bot.api, "post_c2c_message"):
            ret = await bot.api.post_c2c_message(**payload)
        else:
            raise RuntimeError("未找到适用的 QQ OpenAPI HTTP 发送客户端")
    except Exception as e:
        logger.error(f"[send_c2c_message] 发送单聊消息异常: {e}")
        raise

    if stop_event and hasattr(event, "stop_event"):
        event.stop_event()

    return ret


async def send_keyboard(
    event: AstrMessageEvent,
    content: str | dict | QQCKeyboard | list[list[QQCButton]] | None = None,
    keyboard: QQCKeyboard | dict | str | list[list[QQCButton]] | None = None,
    *,
    markdown: str | dict | None = None,
    msg_type: int = 2,
    msg_id: str | None = None,
    msg_seq: int = 1,
    is_wakeup: bool = False,
    stop_event: bool = True,
) -> Any:
    """封装 QQ 官方平台按钮键盘消息的发送逻辑。

    支持群聊（GroupMessage）、私聊（C2CMessage）、频道子频道（Message）以及频道私信（DirectMessage）。
    单聊消息严格对齐官方 OpenAPI v2: POST /v2/users/{user_openid}/messages

    注：QQ 官方已废弃 template_id / custom_template_id 模板机制以及 click_limit / at_bot_show_channel_list 等字段。
    Markdown 消息统一使用原生 content 传递文本；按钮使用 QQCButton / QQCKeyboard 组装。

    :param event: 当前消息事件（QQOfficialMessageEvent 或包含 bot 及 raw_message 的 AstrMessageEvent）
    :param content: 消息正文。当 msg_type=2（默认）时自动包装为 {"content": content}
    :param keyboard: QQCKeyboard 实例、模板 ID 字符串、按钮二维列表或原始 keyboard dict
    :param markdown: Markdown 正文（与 content 等效）
    :param msg_type: 消息类型：0 为纯文本，2 为 Markdown（默认 2）
    :param msg_id: 被回复的消息 ID（缺省时自动从 event / raw_message 获取）
    :param msg_seq: 回复消息的序号，默认 1
    :param is_wakeup: 是否为互动召回消息（单聊场景可用）
    :param stop_event: 发送后是否终止事件传播（默认 True，防止触发后续处理器或 LLM 对话）
    :return: 平台 API 发送结果
    """
    # 兼容参数顺序：如果第 2 个位置参数传了 keyboard，自动交换
    if keyboard is None and isinstance(content, (QQCKeyboard, list)):
        keyboard = content
        content = None
    elif isinstance(content, (QQCKeyboard, list)) and isinstance(keyboard, (str, dict)):
        keyboard, content = keyboard, content

    raw_msg = getattr(getattr(event, "message_obj", None), "raw_message", None)

    # 单聊场景直接委托至专用的 send_c2c_message
    if isinstance(raw_msg, botpy.message.C2CMessage):
        return await send_c2c_message(
            event=event,
            content=content,
            keyboard=keyboard,
            markdown=markdown,
            msg_type=msg_type,
            msg_id=msg_id,
            msg_seq=msg_seq,
            is_wakeup=is_wakeup,
            stop_event=stop_event,
        )

    bot = getattr(event, "bot", None)
    if bot is None or raw_msg is None:
        raise TypeError(
            f"事件 {type(event).__name__} 缺少 bot 或 raw_message，"
            f"请确保在 QQ 官方平台 (QQOfficialMessageEvent) 下调用"
        )

    target_msg_id = (
        msg_id
        or getattr(raw_msg, "id", None)
        or getattr(getattr(event, "message_obj", None), "message_id", None)
    )

    # 1. 转换 keyboard 为 dict
    keyboard_payload: dict | None = None
    if isinstance(keyboard, QQCKeyboard):
        keyboard_payload = keyboard.to_dict()
    elif isinstance(keyboard, str):
        keyboard_payload = {"id": keyboard}
    elif isinstance(keyboard, list):
        keyboard_payload = QQCKeyboard(keyboard).to_dict()
    elif isinstance(keyboard, dict):
        keyboard_payload = keyboard
    elif keyboard is not None:
        raise TypeError(f"不支持的 keyboard 类型: {type(keyboard).__name__}")

    # 2. 处理 markdown / content
    markdown_payload: dict | None = None
    text_content: str | None = None

    if markdown is not None:
        msg_type = 2
        if isinstance(markdown, str):
            markdown_payload = {"content": markdown}
        elif isinstance(markdown, dict):
            markdown_payload = markdown
        else:
            markdown_payload = {"content": str(markdown)}
    elif content is not None:
        if isinstance(content, dict):
            msg_type = 2
            markdown_payload = content
        elif msg_type == 2:
            markdown_payload = {"content": str(content)}
        else:
            text_content = str(content)

    ret = None
    try:
        if isinstance(raw_msg, botpy.message.GroupMessage):
            group_openid = raw_msg.group_openid
            payload: dict[str, Any] = {
                "msg_type": msg_type,
            }
            if target_msg_id:
                payload["msg_id"] = target_msg_id
                payload["msg_seq"] = msg_seq
            if markdown_payload is not None:
                payload["markdown"] = markdown_payload
            if text_content is not None:
                payload["content"] = text_content
            if keyboard_payload is not None:
                payload["keyboard"] = keyboard_payload

            route = Route("POST", "/v2/groups/{group_openid}/messages", group_openid=group_openid)
            if hasattr(bot, "api") and hasattr(bot.api, "_http") and hasattr(bot.api._http, "request"):
                ret = await bot.api._http.request(route, json=payload)
            else:
                ret = await bot.api.post_group_message(group_openid=group_openid, **payload)

        elif isinstance(raw_msg, botpy.message.Message):
            kwargs: dict[str, Any] = {
                "channel_id": raw_msg.channel_id,
            }
            if target_msg_id:
                kwargs["msg_id"] = target_msg_id
            if markdown_payload is not None:
                kwargs["markdown"] = markdown_payload
            if text_content is not None:
                kwargs["content"] = text_content
            if keyboard_payload is not None:
                kwargs["keyboard"] = keyboard_payload

            ret = await bot.api.post_message(**kwargs)

        elif isinstance(raw_msg, botpy.message.DirectMessage):
            kwargs = {
                "guild_id": raw_msg.guild_id,
            }
            if target_msg_id:
                kwargs["msg_id"] = target_msg_id
            if markdown_payload is not None:
                kwargs["markdown"] = markdown_payload
            if text_content is not None:
                kwargs["content"] = text_content
            if keyboard_payload is not None:
                kwargs["keyboard"] = keyboard_payload

            ret = await bot.api.post_dms(**kwargs)

        else:
            raise TypeError(f"未知的 QQ 消息类型: {type(raw_msg).__name__}，无法发送按钮消息")

    except Exception as e:
        logger.error(f"[send_keyboard] 发送按钮消息异常: {e}")
        raise

    if stop_event and hasattr(event, "stop_event"):
        event.stop_event()

    return ret


__all__ = [
    "QQCPermission",
    "QQCButton",
    "QQCKeyboard",
    "send_keyboard",
    "send_c2c_message",
]

