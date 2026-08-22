from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..context import BqyxServices
from ..hooks import error_reply


class HelpHandlers(BqyxServices):
    @error_reply
    @registrar.on_group_command("帮助", "help")
    async def show_help(self, event: GroupMessageEvent) -> None:
        await self.replies.send_help(event)
