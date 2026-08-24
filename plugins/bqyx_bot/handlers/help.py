from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..context import BqyxServices
from ..hooks import (
    TOTAL_CALLS_PER_MINUTE,
    command_rate_limit,
    daily_call_stats_limit,
    error_reply,
    rpm_check_limit,
    total_call_limit,
)


class HelpHandlers(BqyxServices):
    @error_reply
    @command_rate_limit(name="帮助")
    @registrar.on_group_command("帮助", "help")
    async def show_help(self, event: GroupMessageEvent) -> None:
        await self.replies.send_help(event)

    @error_reply
    @rpm_check_limit
    @registrar.on_group_command("统计RPM", "统计rpm")
    async def show_rpm(self, event: GroupMessageEvent) -> None:
        current = total_call_limit.calls_in_period()
        await event.reply(f"当前全局 RPM：{current}/{TOTAL_CALLS_PER_MINUTE}")

    @error_reply
    @daily_call_stats_limit
    @registrar.on_group_command("统计今日调用", "统计今日调用次数")
    async def show_daily_command_calls(self, event: GroupMessageEvent) -> None:
        stats = await self.store.list_command_call_stats()
        total = sum(count for _, count in stats)
        lines = ["今日指令调用统计："]
        lines.extend(f"{command_name}：{count} 次" for command_name, count in stats)
        lines.append(f"总计：{total} 次")
        await event.reply("\n".join(lines))
