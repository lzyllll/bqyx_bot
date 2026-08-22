from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path
from typing import Any

from bqyx_api.render import Renderer
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types.qq import ForwardConstructor


class ReplyService:
    def __init__(self, api: Any, workspace: Path, bot_id: str | None = None) -> None:
        self.api = api
        self.workspace = Path(workspace)
        self.bot_id = bot_id or "123456"

    def set_bot_id(self, bot_id: str | int) -> None:
        self.bot_id = str(bot_id)

    async def send_help(self, event: GroupMessageEvent) -> None:
        fc = ForwardConstructor(user_id=str(event.self_id), nickname="Bot")
        fc.attach_text(
            "BQYX Bot 帮助\n"
            "\n"
            "绑定：\n"
            "绑定军队 <ID>     为本群绑定军队\n"
            "绑定uid <UID> [存档]  绑定个人游戏ID和存档\n"
            "绑定账号 <账号>    用4399账号名绑定\n"
            "一键绑定          自动匹配并绑定\n"
            "我的绑定          查看当前绑定\n"
            "我的信息          查看个人信息\n"
            "我的物品          查看背包，有变动时附带对比图\n"
            "免at添加 @用户    添加到免at名单\n"
            "免at删除 @用户    从免at名单移除\n"
            "免at列表          查看免at名单"
        )
        fc.attach_text(
            "本群查询（需绑定军队）：\n"
            "军队信息 [图片|文本]\n"
            "查成员 [图片|表格|文本]\n"
            "查争霸 [图片|表格|文本]\n"
            "查日贡 [阈值] [图片|表格|文本]\n"
            "查日贡@ [阈值]\n"
            "查周贡 [阈值] [图片|表格|文本]\n"
            "查周贡@ [阈值]"
        )
        await self.api.qq.post_group_forward_msg(event.group_id, fc.build())

    async def send_members(
        self,
        event: GroupMessageEvent,
        members: Any,
        format_type: str = "图片",
        *,
        title: str = "",
        file_prefix: str = "members",
        text_content: str | None = None,
    ) -> None:
        member_list = list(members)
        if format_type == "图片":
            if title:
                await event.reply(title)
            await self._send_image(event, Renderer.members.image(member_list))
            return
        if format_type == "表格":
            await self._send_excel(
                event,
                Renderer.members.excel(member_list),
                file_prefix,
                "正在上传成员表格...",
            )
            return

        reply_text = (text_content or Renderer.members.text(member_list)).strip()
        await self._send_text(event, reply_text)

    async def send_domain(
        self,
        event: GroupMessageEvent,
        members: Any,
        union_info: Any,
        format_type: str = "图片",
        *,
        file_prefix: str = "domain",
    ) -> None:
        member_list = list(members)
        if format_type == "图片":
            await self._send_image(event, Renderer.domain.image(member_list, union_info))
            return
        if format_type == "表格":
            await self._send_excel(
                event,
                Renderer.domain.excel(member_list, union_info),
                file_prefix,
                "正在上传争霸表格...",
            )
            return
        await event.reply(Renderer.domain.text(member_list, union_info))

    async def send_union_info(
        self,
        event: GroupMessageEvent,
        union_info: Any,
        format_type: str = "图片",
    ) -> None:
        if format_type == "图片":
            await self._send_image(event, Renderer.union_info.image(union_info))
            return
        await event.reply(Renderer.union_info.text(union_info))

    async def send_my_things(
        self,
        event: GroupMessageEvent,
        inventory_png: bytes,
        diff_png: bytes | None = None,
    ) -> None:
        """一条聚合消息：我的物品图，有变动时再附一张对比图。"""
        fc = self.build_things_forward(event, inventory_png, diff_png)
        await self.api.qq.post_group_forward_msg(event.group_id, fc)

    def build_things_forward(
        self,
        event: GroupMessageEvent,
        inventory_png: bytes,
        diff_png: bytes | None = None,
    ):
        fc = ForwardConstructor(user_id=str(event.self_id), nickname="Bot")
        fc.attach_image(self._b64_image(inventory_png))
        if diff_png:
            fc.attach_image(self._b64_image(diff_png))
        return fc.build()

    @staticmethod
    def _b64_image(data: bytes) -> str:
        return "base64://" + base64.b64encode(data).decode("utf-8")

    async def send_forward_text(self, event: GroupMessageEvent, text: str) -> None:
        fc = ForwardConstructor(user_id=str(event.self_id), nickname="Bot")
        fc.attach_text(text)
        await self.api.qq.post_group_forward_msg(event.group_id, fc.build())

    async def _send_image(self, event: GroupMessageEvent, image_bytes: bytes) -> None:
        b64_str = base64.b64encode(image_bytes).decode("utf-8")
        await self.api.qq.post_group_msg(
            group_id=event.group_id,
            image=f"base64://{b64_str}",
        )

    async def _send_excel(
        self,
        event: GroupMessageEvent,
        excel_bytes: bytes,
        file_prefix: str,
        notice: str,
    ) -> None:
        save_dir = self.workspace / "xlsx"
        save_dir.mkdir(parents=True, exist_ok=True)
        date_str = time.strftime("%Y-%m-%d_%H-%M-%S")
        file_name = f"{file_prefix}_{event.group_id}_{date_str}.xlsx"
        file_path = save_dir / file_name
        file_path.write_bytes(excel_bytes)
        await event.reply(notice)
        try:
            await self.api.qq.send_group_file(
                event.group_id,
                str(file_path),
                name=file_name,
            )
            await asyncio.sleep(10)
        finally:
            if file_path.exists():
                file_path.unlink()

    async def _send_text(self, event: GroupMessageEvent, text: str) -> None:
        if len(text) > 400:
            await self.send_forward_text(event, text)
            return
        await event.reply(text)
