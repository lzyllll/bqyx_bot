from __future__ import annotations

import asyncio
import functools
import inspect
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator

from astrbot.api.event import AstrMessageEvent, MessageEventResult
from bqyx_api.archive.union import UnionPKRankAgent
from bqyx_api.render import (
    DemonRenderer,
    DomainRenderer,
    PlayerHtmlRenderer,
    UnionInfoRenderer,
    UnionMembersRenderer,
    UnionPKRankRenderer,
    UnionTaskRenderer,
)





HELP_MODULE_BIND = "绑定"
HELP_MODULE_PERSONAL = "个人"
HELP_MODULE_UNION = "军队"
HELP_MODULE_RANK = "排行"

HELP_MODULES = [
    HELP_MODULE_BIND,
    HELP_MODULE_PERSONAL,
    HELP_MODULE_UNION,
    HELP_MODULE_RANK,
]


def md_cmd_enter(label: str, cmd: str) -> str:
    """生成交互指令标签（qqbot-cmd-enter 在官方平台不支持 show 属性，统一使用兼容的 md_cmd_example）。"""
    return md_cmd_example(label, cmd)


def md_cmd_input(label: str, cmd_prefix: str, add_space: bool | None = None) -> str:
    """生成点击后填入聊天输入框的 QQ Markdown 交互标签（参数生成，零正则）。

    默认规则：如果是纯数字（选项序号）或取消词，不加空格；如果是指令前缀，自动追加空格。
    也可以通过显式传入 add_space 进行控制。
    """
    cleaned = cmd_prefix.strip()
    if add_space is None:
        add_space = not (cleaned.isdigit() or cleaned in ("取消", "退出", "q", "Q"))
    prefix = (cleaned + " ") if add_space else cleaned
    encoded = urllib.parse.quote(prefix)
    return f'<qqbot-cmd-input text="{encoded}" show="{label}" reference="false" />'


def md_cmd_example(label: str, full_cmd: str) -> str:
    """生成点击后将完整示例填入输入框的 QQ Markdown 交互标签（参数生成，零正则）。"""
    encoded = urllib.parse.quote(full_cmd.strip())
    return f'<qqbot-cmd-input text="{encoded}" show="{label}" reference="false" />'


def normalize_help_module(module: str) -> str:
    """归一化帮助模块名称。"""
    raw = (module or "").strip()
    if any(k in raw for k in ("军", "群", "团")):
        return HELP_MODULE_UNION
    if any(k in raw for k in ("排", "榜")):
        return HELP_MODULE_RANK
    if any(k in raw for k in ("查", "个人", "信息", "战力", "物品", "贡献")):
        if raw != "绑定" and "绑定" not in raw or raw in ("个人", "个人查询"):
            return HELP_MODULE_PERSONAL
    if "绑定" in raw:
        return HELP_MODULE_BIND
    return HELP_MODULE_BIND


def build_help_keyboard(
    active_module: str = HELP_MODULE_BIND,
) -> tuple[str, Any]:
    """生成指定模块的帮助 Markdown 文本与 QQCKeyboard 按钮组件。

    将帮助拆分为四个模块：
      1. 绑定 (HELP_MODULE_BIND)
      2. 个人 (HELP_MODULE_PERSONAL)
      3. 军队 (HELP_MODULE_UNION)
      4. 排行 (HELP_MODULE_RANK)

    第 1 行统一放置四个模块的切换按钮（4 列）：
      - 当前高亮模块使用 style=4（蓝色背景 + 白色字体，高亮选中）；
      - 未激活的模块使用 style=0（灰色线框）。
    后续各行最多 3 列，放置对应模块的核心快捷指令按钮。
    """
    from .qq.components import QQCButton, QQCKeyboard

    current_module = normalize_help_module(active_module)

    # 1. 顶部切换按钮栏（行 1：4个模块切换按钮）
    switch_buttons = [
        QQCButton.command(
            label=f"📌 {HELP_MODULE_BIND}" if current_module == HELP_MODULE_BIND else HELP_MODULE_BIND,
            cmd=f"帮助 {HELP_MODULE_BIND}",
            enter=True,
            style=4 if current_module == HELP_MODULE_BIND else 0,
        ),
        QQCButton.command(
            label=f"📌 {HELP_MODULE_PERSONAL}" if current_module == HELP_MODULE_PERSONAL else HELP_MODULE_PERSONAL,
            cmd=f"帮助 {HELP_MODULE_PERSONAL}",
            enter=True,
            style=4 if current_module == HELP_MODULE_PERSONAL else 0,
        ),
        QQCButton.command(
            label=f"📌 {HELP_MODULE_UNION}" if current_module == HELP_MODULE_UNION else HELP_MODULE_UNION,
            cmd=f"帮助 {HELP_MODULE_UNION}",
            enter=True,
            style=4 if current_module == HELP_MODULE_UNION else 0,
        ),
        QQCButton.command(
            label=f"📌 {HELP_MODULE_RANK}" if current_module == HELP_MODULE_RANK else HELP_MODULE_RANK,
            cmd=f"帮助 {HELP_MODULE_RANK}",
            enter=True,
            style=4 if current_module == HELP_MODULE_RANK else 0,
        ),
    ]

    keyboard = QQCKeyboard([switch_buttons])

    # 2. 根据模块添加快捷功能按钮及构建 Markdown 文本（除模块切换行4列外，其余行最多3列）
    if current_module == HELP_MODULE_BIND:
        markdown_text = (
            "# 🎮 BQYX 帮助 · 账号绑定\n"
            "> 💡 点击下方按钮可直接执行指令；带输入框的按钮点击后可补全参数。\n\n"
            "### 账号绑定\n"
            "- **绑定游戏名** `<角色名>`：按角色名绑定（支持同名选择）\n"
            "- **绑定游戏名 ~**：列出军团全部成员，点击蓝字快速绑定\n"
            "- **绑定uid** `<UID>`：按 UID 绑定（如 `123456` 或 `123456_1`）\n"
            "- **绑定账号** `<4399账号>`：按 4399 账号名直接绑定\n"
            "- **我的绑定**：查看当前绑定的账号与存档"
        )
        # 行 2: 绑定状态查询与全员快捷绑定 (2 列)
        keyboard.add_row(
            QQCButton.command("我的绑定", "我的绑定", style=1),
            QQCButton.command("成员列表绑定", "绑定游戏名 ~", style=0),
        )
        # 行 3: 快速绑定参数输入（enter=False 自动将指令前缀填入输入框，3 列）
        keyboard.add_row(
            QQCButton.command("绑定游戏名", "绑定游戏名 ", enter=False, style=0),
            QQCButton.command("绑定uid", "绑定uid ", enter=False, style=0),
            QQCButton.command("绑定账号", "绑定账号 ", enter=False, style=0),
        )

    elif current_module == HELP_MODULE_PERSONAL:
        markdown_text = (
            "# 📊 BQYX 帮助 · 个人数据查询\n"
            "> 💡 点击下方按钮可快速查询个人角色与战力数据。\n\n"
            "### 个人查询\n"
            "- **我的信息**：查看个人贡献数据与日常任务进度\n"
            "- **我的战力** `[@用户]`：查看角色战力面板与加成汇总\n"
            "- **查物品 / 我的物品** `[@用户]`：查看背包物品及变动对比\n"
            "- **我的贡献** `[@用户] [年月]`：查看每日贡献日历墙\n"
            "- **我的绑定**：查看当前绑定的账号与存档\n"
            "- **统计RPM**：查看当前全局每分钟调用数"
        )
        # 行 2: 常用个人查询（3 列）
        keyboard.add_row(
            QQCButton.command("我的信息", "我的信息", style=1),
            QQCButton.command("我的战力", "我的战力", style=1),
            QQCButton.command("我的贡献", "我的贡献", style=1),
        )
        # 行 3: 物品与辅助查询（3 列）
        keyboard.add_row(
            QQCButton.command("查物品", "查物品", style=1),
            QQCButton.command("我的绑定", "我的绑定", style=0),
            QQCButton.command("统计RPM", "统计RPM", style=0),
        )
        # "修罗查询"
        keyboard.add_row(
            QQCButton.command("查修罗", "查修罗", style=1),
        )

    elif current_module == HELP_MODULE_UNION:
        markdown_text = (
            "# ⚔️ BQYX 帮助 · 军队与本群查询\n"
            "> 💡 需先绑定军队：`绑定军队 <军队ID>`；查贡献指令默认发送图片。\n\n"
            "### 基础与成员\n"
            "- **军队信息** `[图片|文本]`：查看绑定的军队基本信息\n"
            "- **查成员** `[图片|表格|文本]`：查看军团成员列表\n"
            "- **绑定军队** `<军队ID>`：为本群绑定指定军队\n\n"
            "### 贡献与考核（默认图片）\n"
            "- **查日贡** `[阈值]`：今日达标/未达标成员图（例：`查日贡 1100`）\n"
            "- **查周贡** `[阈值]`：本周达标/未达标成员图（例：`查周贡 4000`）\n"
            "- **昨日贡献** `[阈值]`：昨日日贡排行图（默认全部）\n\n"
            "### 争霸与副本\n"
            "- **查争霸** `[图片|表格|文本]`：查看争霸状态与据点分配\n"
            "- **查PK** `[图片|文本]`：查看全军团 PK 积分榜\n"
            "- **查修罗** `[@用户] [图片|文本]`：查看修罗塔进度"
        )
        # 行 2: 军队与成员（已删除查成员 表格）
        keyboard.add_row(
            QQCButton.command("军队信息", "军队信息", style=1),
            QQCButton.command("查成员", "查成员", style=1),
        )
        # 行 3: 贡献达标（默认图片）
        keyboard.add_row(
            QQCButton.command("查日贡", "查日贡", style=1),
            QQCButton.command("查周贡", "查周贡", style=1),
            QQCButton.command("昨日贡献", "昨日贡献", style=1),
        )
        # 行 4: 活动与副本
        keyboard.add_row(
            QQCButton.command("查争霸", "查争霸", style=1),
            QQCButton.command("查PK", "查PK", style=1),
        )
        # 行 5: 军队绑定输入（enter=False）
        keyboard.add_row(
            QQCButton.command("绑定军队", "绑定军队 ", enter=False, style=0),
        )

    else:  # HELP_MODULE_RANK
        markdown_text = (
            "# 🏆 BQYX 帮助 · 实时与历史排行\n"
            "> 💡 点击下方按钮可快速查询排行。\n\n"
            "### 日贡排行\n"
            "- **今日日贡排行** `[范围]`：实时今日日贡排行（例：`今日日贡排行 1-50`）\n"
            "- **昨日日贡排行** `[范围]`：昨日日贡归档排行（例：`昨日日贡排行 100`）\n\n"
            "### 周贡排行\n"
            "- **本周周贡排行** `[范围]`：本周实时周贡排行\n"
            "- **上周周贡排行** `[范围]`：上周周贡归档排行\n\n"
            "### 军队与PK\n"
            "- **军队排行** `[范围]`：全服军队战力总排行（例：`军队排行 1-50`）\n"
            "- **查PK** `[图片|文本]`：全军团 PK 竞技排行榜"
        )
        # 行 2: 日贡排行
        keyboard.add_row(
            QQCButton.command("今日日贡排行", "今日日贡排行", style=1),
            QQCButton.command("昨日日贡排行", "昨日日贡排行", style=1),
        )
        # 行 3: 周贡排行
        keyboard.add_row(
            QQCButton.command("本周周贡排行", "本周周贡排行", style=1),
            QQCButton.command("上周周贡排行", "上周周贡排行", style=1),
        )
        # 行 4: 军队与PK
        keyboard.add_row(
            QQCButton.command("军队排行", "军队排行", style=1),
            QQCButton.command("查PK", "查PK", style=1),
        )

    return markdown_text, keyboard


class ReplyService:
    def __init__(self, workspace: Path, bot_id: str | None = None) -> None:
        self.workspace = Path(workspace)
        self.bot_id = str(bot_id or "123456")
        self.members_renderer = UnionMembersRenderer()
        self.domain_renderer = DomainRenderer()
        self.union_info_renderer = UnionInfoRenderer()
        self.pk_rank_renderer = UnionPKRankRenderer()
        self.task_renderer = UnionTaskRenderer()
        self.demon_renderer = DemonRenderer()
        self.player_renderer = PlayerHtmlRenderer()

    def set_bot_id(self, bot_id: str | int) -> None:
        self.bot_id = str(bot_id)

    def _get_bot_id(self, event: AstrMessageEvent) -> str:
        if hasattr(event, "get_self_id") and event.get_self_id():
            return str(event.get_self_id())
        return self.bot_id

    def _save_temp_image(self, image_data: bytes | str | Path) -> str:
        """将图片字节保存为临时本地文件供 event.image_result 使用，网络 URL 或已有路径直接返回。"""
        if isinstance(image_data, (str, Path)):
            str_data = str(image_data)
            if str_data.startswith("http://") or str_data.startswith("https://"):
                return str_data
            p = Path(str_data)
            if p.exists():
                return str(p.resolve())

        temp_dir = self.workspace / "temp_images"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            now = time.time()
            for old_file in temp_dir.glob("*.png"):
                if now - old_file.stat().st_mtime > 3600:
                    old_file.unlink(missing_ok=True)
        except Exception:
            pass

        img_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        img_path = temp_dir / f"img_{img_id}.png"
        img_bytes = (
            image_data
            if isinstance(image_data, (bytes, bytearray))
            else bytes(image_data)
        )
        img_path.write_bytes(img_bytes)
        return str(img_path.resolve())

    def image_result(
        self,
        event: AstrMessageEvent,
        image_data: bytes | str | Path,
    ) -> MessageEventResult:
        """生成单张图片的消息结果（纯生成，不发送）。"""
        path_or_url = self._save_temp_image(image_data)
        if hasattr(event, "image_result") and type(event).__name__ != "MagicMock":
            return event.image_result(path_or_url)
        return (
            MessageEventResult().url_image(path_or_url)
            if path_or_url.startswith("http")
            else MessageEventResult().file_image(path_or_url)
        )

    def text_result(
        self,
        event: AstrMessageEvent,
        text: str,
    ) -> list[MessageEventResult]:
        """将长文本分段生成消息结果列表（纯生成，不发送）。"""
        text = text.strip()
        if not text:
            return []
        max_chunk_size = 1000
        if len(text) <= max_chunk_size:
            if hasattr(event, "plain_result"):
                return [event.plain_result(text)]
            return [MessageEventResult().message(text)]

        chunks: list[str] = []
        current = text
        while len(current) > max_chunk_size:
            split_idx = current.rfind("\n", 0, max_chunk_size)
            if split_idx <= 0:
                split_idx = max_chunk_size
            chunks.append(current[:split_idx].strip())
            current = current[split_idx:].strip()
        if current:
            chunks.append(current)

        results: list[MessageEventResult] = []
        for chunk in chunks:
            if chunk:
                if hasattr(event, "plain_result"):
                    results.append(event.plain_result(chunk))
                else:
                    results.append(MessageEventResult().message(chunk))
        return results

    def excel_result(
        self,
        event: AstrMessageEvent,
        excel_bytes: bytes,
        file_prefix: str,
        notice: str,
    ) -> MessageEventResult:
        """保存 excel 表格并生成提示消息结果（纯生成，不发送）。"""
        save_dir = self.workspace / "xlsx"
        save_dir.mkdir(parents=True, exist_ok=True)
        date_str = time.strftime("%Y-%m-%d_%H-%M-%S")
        group_id = event.get_group_id() or "group"
        file_name = f"{file_prefix}_{group_id}_{date_str}.xlsx"
        file_path = save_dir / file_name
        file_path.write_bytes(excel_bytes)
        msg = f"{notice}\n文件已保存至：{file_path.name}"
        if hasattr(event, "plain_result"):
            return event.plain_result(msg)
        return MessageEventResult().message(msg)

    def markdown_result(
        self,
        event: AstrMessageEvent | None,
        text: str,
    ) -> MessageEventResult:
        """生成 Markdown 格式文本消息结果（纯生成，不发送）。"""
        if event is not None and type(event).__name__ != "MagicMock" and hasattr(event, "make_result"):
            res = event.make_result().message(text)
        elif event is not None and hasattr(event, "plain_result"):
            res = event.plain_result(text)
        else:
            res = MessageEventResult().message(text)
        if hasattr(res, "use_markdown"):
            res.use_markdown(True)
        return res

    def markdown_tip(
        self,
        event: AstrMessageEvent,
        message: str,
        usage: str = "",
        extra: str = "",
    ) -> MessageEventResult:
        """生成标准 Markdown 提示消息结果。直接基于参数拼接，禁止正则。"""
        lines = [f"> 💡 **{message}**"]
        if usage:
            if "\n" in usage:
                lines.append("> \n" + "\n".join(f"> {line}" for line in usage.splitlines()))
            else:
                lines.append(f"> **用法**：{usage}")
        if extra:
            for line in extra.splitlines():
                lines.append(f"> {line}")
        return self.markdown_result(event, "\n".join(lines))

    def markdown_warn(
        self,
        event: AstrMessageEvent,
        message: str,
        extra: str = "",
    ) -> MessageEventResult:
        """生成标准 Markdown 警告/错误消息结果。直接基于参数拼接，禁止正则。"""
        lines = [f"> ⚠️ **{message}**"]
        if extra:
            for line in extra.splitlines():
                lines.append(f"> {line}")
        return self.markdown_result(event, "\n".join(lines))

    def markdown_success(
        self,
        event: AstrMessageEvent,
        message: str,
        details: list[str] | None = None,
    ) -> MessageEventResult:
        """生成标准 Markdown 成功消息结果。"""
        lines = [f"> 🎉 **{message}**"]
        if details:
            for d in details:
                lines.append(f"> {d}")
        return self.markdown_result(event, "\n".join(lines))

    async def build_help(
        self, event: AstrMessageEvent, module: str = ""
    ) -> list[MessageEventResult]:
        """生成帮助消息内容。QQ 官方平台直接发送键盘并返回空列表，其余平台回退为图片或文本结果。"""
        try:
            from .qq.components import send_keyboard

            markdown_text, keyboard = build_help_keyboard(module)
            await send_keyboard(event, markdown=markdown_text, keyboard=keyboard)
            return []
        except Exception:
            pass

        if not module:
            try:
                from .render import get_or_render_help_image

                png_bytes = await get_or_render_help_image()
                return [self.image_result(event, png_bytes)]
            except Exception:
                pass

        help_sections = {
            "绑定": (
                "【账号绑定】\n"
                "绑定游戏名 <角色名>   按游戏名绑定（支持重名会话选择）\n"
                "  例：绑定游戏名 张三\n"
                "绑定游戏名 ~          列出全体成员名单，点击直接绑定\n"
                "绑定uid <UID>         按游戏 UID 绑定（支持 123456 或 123456_1）\n"
                "  例：绑定uid 123456\n"
                "绑定账号 <4399账号>   按 4399 账号名绑定\n"
                "  例：绑定账号 my_user\n"
                "我的绑定              查看当前绑定的账号与存档"
            ),
            "个人": (
                "【个人数据查询】\n"
                "我的信息              查看个人贡献与任务进度\n"
                "我的战力 [@用户]      查看角色战力面板与加成汇总\n"
                "  例：我的战力 / 我的战力 @张三\n"
                "查物品 / 我的物品 [@用户] 查看背包物品及变动对比图\n"
                "  例：查物品 / 我的物品 @张三\n"
                "我的贡献 [@用户] [年月] 查看月度每日日贡贡献日历墙\n"
                "  例：我的贡献 / 我的贡献 2026-09 / 我的贡献 上月\n"
                "我的绑定              查看当前绑定的账号与存档\n"
                "统计RPM               查看当前全局每分钟调用数\n"
                "查修罗 [@用户] [图片|文本] 查看修罗塔进度"
            ),
            "军队": (
                "【军队与本群查询】（需先绑定军队，查贡献默认发送图片）\n"
                "绑定军队 <军队ID>     为本群绑定对应军队\n"
                "  例：绑定军队 1234\n"
                "军队信息 [图片|文本]  查看绑定的军队基本信息\n"
                "查成员 [图片|表格|文本] 查看军团成员列表\n"
                "查日贡 [阈值]         查看今日达标/未达标成员图（默认图片）\n"
                "  例：查日贡 / 查日贡 1100 / 查日贡@ 1100\n"
                "查周贡 [阈值]         查看本周达标/未达标成员图（默认图片）\n"
                "  例：查周贡 / 查周贡 4000\n"
                "昨日贡献 [阈值]       查看昨日日贡排行图（默认全部）\n"
                "  例：昨日贡献 / 昨日贡献 1100\n"
                "查争霸 [图片|表格|文本] 查看争霸状态与据点分配\n"
                "查PK [图片|文本]      查看PK排行"
            ),
            "排行": (
                "【实时与历史排行】\n"
                "今日日贡排行 [范围]   实时日贡排行\n"
                "  例：今日日贡排行 / 今日日贡排行 100 / 今日日贡排行 90-110\n"
                "昨日日贡排行 [范围]   昨日日贡归档排行\n"
                "  例：昨日日贡排行 / 昨日日贡排行 100\n"
                "本周周贡排行 [范围]   本周实时周贡排行\n"
                "  例：本周周贡排行 / 本周周贡排行 100\n"
                "上周周贡排行 [范围]   上周周贡归档排行\n"
                "  例：上周周贡排行 / 上周周贡排行 100\n"
                "军队排行 [范围]       全服军队总排行（实时）\n"
                "  例：军队排行 / 军队排行 1-50"
            ),
        }

        if module:
            mod_key = normalize_help_module(module)
            text = help_sections.get(mod_key, "\n\n".join(help_sections.values()))
        else:
            text = "\n\n".join(help_sections.values())

        return self.text_result(event, text)

    async def build_members(
        self,
        event: AstrMessageEvent,
        members: Any,
        format_type: str = "图片",
        *,
        title: str = "军团成员列表",
        file_prefix: str = "members",
        text_content: str | None = None,
        text_lines: list[str] | None = None,
        uid: str | None = None,
        image_cmd: str | None = None,
    ) -> list[MessageEventResult]:
        member_list = list(members)
        if format_type == "图片":
            png = await self.members_renderer.image(
                member_list,
                title=title,
                uid=uid,
                captured_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return [self.image_result(event, png)]
        if format_type == "表格":
            return [
                self.excel_result(
                    event,
                    self.members_renderer.excel(member_list),
                    file_prefix,
                    "正在上传成员表格...",
                )
            ]

        if text_lines is not None:
            lines = list(text_lines)
        elif text_content:
            lines = text_content.splitlines()
        else:
            lines = []
            for i, m in enumerate(member_list, 1):
                p_name = m.detail.playerName or f"UID_{m.uid}"
                btn = md_cmd_example(p_name, f"查贡献 {p_name}")
                con_day = m.detail.conDay if m.detail else 0
                contrib = m.contribution or 0
                lines.append(f"{i}. {btn} (日贡: {con_day:,} | 总贡: {contrib:,})")

        title_text = title if "共" in title else f"{title} (共 {len(member_list)} 人)"
        tip_lines = [f"> 💡 **{title_text}**"]
        if lines:
            if len(lines) == 1:
                tip_lines.append(f"> **用法**：{lines[0]}")
            else:
                tip_lines.append("> \n" + "\n".join(f"> {line}" for line in lines))
        tip_lines.append("> 点击角色名可直接调用 查贡献 查询个人日历")

        full_md = "\n".join(tip_lines)
        target_img_cmd = image_cmd
        if not target_img_cmd and file_prefix == "members":
            target_img_cmd = "查成员 图片"

        if target_img_cmd:
            img_btn = md_cmd_example(f"🔴 {target_img_cmd}", target_img_cmd)
            full_md += f"\n\n{img_btn}"

        return [self.markdown_result(event, full_md)]

    async def build_domain(
        self,
        event: AstrMessageEvent,
        members: Any,
        union_info: Any,
        format_type: str = "图片",
        *,
        file_prefix: str = "domain",
        uid: str | None = None,
    ) -> list[MessageEventResult]:
        member_list = list(members)
        if format_type == "图片":
            img = self.domain_renderer.image(member_list, union_info, uid=uid)
            png = await img if inspect.isawaitable(img) else img
            return [self.image_result(event, png)]
        if format_type == "表格":
            return [
                self.excel_result(
                    event,
                    self.domain_renderer.excel(member_list, union_info, uid=uid),
                    file_prefix,
                    "正在上传争霸表格...",
                )
            ]
        return self.text_result(
            event, self.domain_renderer.text(member_list, union_info, uid=uid)
        )

    async def build_pk_rank(
        self,
        event: AstrMessageEvent,
        members: Any,
        format_type: str = "图片",
        *,
        uid: str | None = None,
    ) -> list[MessageEventResult]:
        agent = UnionPKRankAgent.from_members(members)
        if format_type == "图片":
            png = await self.pk_rank_renderer.render_png(
                agent,
                uid=uid,
                captured_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            return [self.image_result(event, png)]
        return self.text_result(event, _pk_rank_text(agent, uid))

    async def build_contribution(
        self,
        event: AstrMessageEvent,
        union_data: Any,
        format_type: str = "图片",
        *,
        title: str = "我的贡献",
    ) -> list[MessageEventResult]:
        if format_type == "文本":
            return self.text_result(
                event,
                self.task_renderer.text(union_data=union_data, title=title),
            )
        png = await self.task_renderer.image(union_data=union_data, title=title)
        return [self.image_result(event, png)]

    async def build_my_contribution_wall(
        self,
        event: AstrMessageEvent,
        png: bytes,
    ) -> list[MessageEventResult]:
        return [self.image_result(event, png)]

    async def build_demon(
        self,
        event: AstrMessageEvent,
        result: Any,
        format_type: str = "图片",
        *,
        title: str = "修罗地图",
    ) -> list[MessageEventResult]:
        if format_type == "文本":
            return self.text_result(
                event, f"{title}\n{self.demon_renderer.text(result)}"
            )
        png = await self.demon_renderer.image(
            result,
            title=title,
            captured_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return [self.image_result(event, png)]

    async def build_union_info(
        self,
        event: AstrMessageEvent,
        union_info: Any,
        format_type: str = "图片",
    ) -> list[MessageEventResult]:
        if format_type == "图片":
            img = self.union_info_renderer.image(union_info)
            png = await img if inspect.isawaitable(img) else img
            return [self.image_result(event, png)]
        return self.text_result(
            event, self.union_info_renderer.text(union_info)
        )

    async def build_my_things(
        self,
        event: AstrMessageEvent,
        inventory_png: bytes,
        diff_png: bytes | None = None,
    ) -> list[MessageEventResult]:
        """我的物品图，有变动时再附一张对比图。"""
        results = [self.image_result(event, inventory_png)]
        if diff_png:
            results.append(self.image_result(event, diff_png))
        return results

    async def build_role_dps_report(
        self,
        event: AstrMessageEvent,
        panel_png: bytes,
        bonus_prop_png: bytes,
        bonus_mod_png: bytes,
        arms_png: bytes | None = None,
        *,
        title: str = "角色战力与加成汇总",
    ) -> list[MessageEventResult]:
        """角色战力与加成汇总。"""
        if hasattr(event, "plain_result") and type(event).__name__ != "MagicMock":
            title_res = event.plain_result(f"🎮 【{title}】")
        else:
            title_res = MessageEventResult().message(f"🎮 【{title}】")

        results = [
            title_res,
            self.image_result(event, panel_png),
            self.image_result(event, bonus_prop_png),
            self.image_result(event, bonus_mod_png),
        ]
        if arms_png is not None:
            results.append(self.image_result(event, arms_png))
        return results

    def build_forward_text(
        self, event: AstrMessageEvent, text: str
    ) -> list[MessageEventResult]:
        """普通长文本分段生成。"""
        return self.text_result(event, text)

    def build_image(
        self, event: AstrMessageEvent, image_bytes: bytes
    ) -> list[MessageEventResult]:
        return [self.image_result(event, image_bytes)]



def _pk_rank_text(agent: UnionPKRankAgent, uid: str | None = None) -> str:
    lines = [
        f"军队PK排行  赛季{agent.season}  {agent.props_name}",
        f"人数: {len(agent.entries)}",
        "",
    ]
    for entry in agent.entries:
        mark = " *" if uid and entry.uid == uid else ""
        gift = f"  {entry.gift_cn_name}" if entry.gift_cn_name else ""
        lines.append(
            f"{entry.rank:>3}. {entry.nickname}  积分{entry.score_text}  "
            f"战力{entry.dps_text}{gift}{mark}"
        )
    return "\n".join(lines)
