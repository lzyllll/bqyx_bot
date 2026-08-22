from bqyx_api.archive.things import ThingsDiff
from ncatbot.core import registrar
from ncatbot.event.qq import GroupMessageEvent

from ..context import BqyxServices
from ..errors import UserNotBoundError
from ..hooks import error_reply, query_limit


def has_item_changes(diff: ThingsDiff | None) -> bool:
    """有上次快照且确实发生了增减/数量变化，才附带变动图。"""
    return diff is not None and not diff.is_empty


class ThingsHandlers(BqyxServices):
    @error_reply
    @query_limit
    @registrar.on_group_command("我的物品")
    async def show_my_things(self, event: GroupMessageEvent) -> None:
        bind = await self.store.get_user_bind(str(event.group_id), str(event.user_id))
        if not bind:
            raise UserNotBoundError()

        user = await self.account.get_user()
        result = await self.things.capture_for(user, bind.uid, bind.arch_index)
        inventory_png = await self.things.render_inventory(
            result.group,
            captured_at=result.snapshot.captured_at,
        )
        diff_png = None
        if has_item_changes(result.diff):
            diff_png = await self.things.render_diff(result.diff)
        await self.replies.send_my_things(event, inventory_png, diff_png)
