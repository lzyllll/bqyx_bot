from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..context import BqyxServices
from ..hooks import TOTAL_CALLS_PER_MINUTE, error_reply, query_limit, total_call_limit,rpm_check_limit


class HelpHandlers(BqyxServices):
    @error_reply
    @query_limit
    @registrar.on_group_command("帮助", "help")
    async def show_help(self, event: GroupMessageEvent) -> None:
        await self.replies.send_help(event)

    @error_reply
    @rpm_check_limit
    @registrar.on_group_command("统计RPM", "统计rpm")
    async def show_rpm(self, event: GroupMessageEvent) -> None:
        current = total_call_limit.calls_in_period()
        await event.reply(f"当前全局 RPM：{current}/{TOTAL_CALLS_PER_MINUTE}")
