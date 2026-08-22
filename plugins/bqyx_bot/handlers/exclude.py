from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types import At

from ..context import BqyxServices
from ..hooks import error_reply


class ExcludeHandlers(BqyxServices):
    @error_reply
    @registrar.on_group_command("免at添加")
    async def add_exclude_at(self, event: GroupMessageEvent, target: At) -> None:
        group_id = str(event.group_id)
        target_qq = str(target.user_id)
        added = await self.store.add_exclude(group_id, target_qq)
        if added:
            await event.reply(f"已将 {target_qq} 添加到本群免at名单")
            return
        await event.reply(f"{target_qq} 已在本群免at名单中")

    @error_reply
    @registrar.on_group_command("免at删除")
    async def remove_exclude_at(self, event: GroupMessageEvent, target: At) -> None:
        group_id = str(event.group_id)
        target_qq = str(target.user_id)
        removed = await self.store.remove_exclude(group_id, target_qq)
        if removed:
            await event.reply(f"已将 {target_qq} 从本群免at名单移除")
            return
        await event.reply(f"{target_qq} 不在本群免at名单中")

    @error_reply
    @registrar.on_group_command("免at列表")
    async def list_exclude_at(self, event: GroupMessageEvent) -> None:
        exclude_list = await self.store.list_exclude(str(event.group_id))
        if not exclude_list:
            await event.reply("本群免at名单为空")
            return
        await event.reply("本群免at名单：\n" + "\n".join(exclude_list))
