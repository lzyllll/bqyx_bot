from bqyx_api.archive.things import ThingsDiff
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent
from ncatbot.types import At

from ..context import BqyxServices
from ..errors import BotError, UserNotBoundError
from ..hooks import command_rate_limit, error_reply


def has_item_changes(diff: ThingsDiff | None) -> bool:
    """有上次快照且确实发生了增减/数量变化，才附带变动图。"""
    return diff is not None and not diff.is_empty


class ThingsHandlers(BqyxServices):
    @error_reply
    @command_rate_limit(name="查物品")
    @registrar.on_group_command("查物品")
    async def check_things(
        self,
        event: GroupMessageEvent,
        target: At | None = None,
    ) -> None:
        qq_id = str(target.user_id if target else event.user_id)
        bind = await self.store.get_user_bind(str(event.group_id), qq_id)
        if not bind:
            if target is None:
                raise UserNotBoundError()
            raise BotError("被 @ 的用户尚未在本群绑定游戏账号。")

        user = await self.account.get_user()
        result = await self.things.capture_for(user, bind.uid, bind.arch_index)
        title = "我的物品" if target is None else f"QQ {qq_id} 的物品"
        inventory_png = await self.things.render_inventory(
            result.group,
            captured_at=result.snapshot.captured_at,
            title=title,
        )
        diff_png = None
        if has_item_changes(result.diff):
            diff_png = await self.things.render_diff(result.diff, title=f"{title}变动")
        await self.replies.send_my_things(event, inventory_png, diff_png)
