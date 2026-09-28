from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, filter

from ..context import BqyxServices
from ..hooks import (
    TOTAL_CALLS_PER_MINUTE,
    command_rate_limit,
    daily_call_stats_limit,
    error_reply,
    rpm_check_limit,
    total_call_limit,
)
from ..parsing import extract_command_arg


class HelpHandlers(BqyxServices):
    # @error_reply
    # @command_rate_limit(name="帮助")
    @filter.command("帮助", alias={"help"})
    async def show_help(self, event: AstrMessageEvent, module: str = ""):
        clean_module = extract_command_arg(
            module, event, ("帮助", "help", "/帮助", "/help")
        ).strip()
        for res in await self.replies.build_help(event, module=clean_module):
            yield res

    @filter.command("统计RPM", alias={"统计rpm"})
    @error_reply
    @rpm_check_limit
    async def show_rpm(self, event: AstrMessageEvent) -> None:
        from ..hooks import _send_reply

        current = total_call_limit.calls_in_period()
        await _send_reply(event, f"当前全局 RPM：{current}/{TOTAL_CALLS_PER_MINUTE}")

    @filter.command("统计今日调用", alias={"统计今日调用次数"})
    @error_reply
    @daily_call_stats_limit
    async def show_daily_command_calls(self, event: AstrMessageEvent) -> None:
        from ..hooks import _send_reply

        stats = await self.store.list_command_call_stats()
        total = sum(count for _, count in stats)
        lines = ["今日指令调用统计："]
        lines.extend(f"{command_name}：{count} 次" for command_name, count in stats)
        lines.append(f"总计：{total} 次")
        await _send_reply(event, "\n".join(lines))
