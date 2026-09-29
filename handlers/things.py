from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, filter
from bqyx_api.archive.things import ThingsDiff

from ..context import BqyxServices
from ..errors import BotError, UserNotBoundError
from ..hooks import command_rate_limit, error_reply
from ..models import UserBind
from ..parsing import extract_at


def has_item_changes(diff: ThingsDiff | None) -> bool:
    """有上次快照且确实发生了增减/数量变化，才附带变动图。"""
    return diff is not None and not diff.is_empty


class ThingsHandlers(BqyxServices):
    @error_reply
    @command_rate_limit(name="查物品")
    @filter.command("查物品", alias={"我的物品"})
    async def check_things(
        self,
        event: AstrMessageEvent,
        target: str = "",
    ) -> None:
        group_id = str(event.get_group_id() or "")
        target_at = extract_at(event, target)
        qq_id = str(target_at.user_id if target_at else event.get_sender_id())
        if group_id:
            bind = await self.store.get_user_bind(group_id, qq_id)
        else:
            p_bind = await self.store.get_private_user_bind(qq_id)
            bind = (
                UserBind(
                    group_id="",
                    qq_id=p_bind.qq_id,
                    uid=p_bind.uid,
                    arch_index=p_bind.arch_index,
                )
                if p_bind
                else None
            )
        if not bind:
            if target_at is None:
                raise UserNotBoundError()
            raise BotError("被 @ 的用户尚未绑定游戏账号。")

        user = await self.account.get_user()
        result = await self.things.capture_for(user, bind.uid, bind.arch_index)
        title = "我的物品" if target_at is None else f"QQ {qq_id} 的物品"
        inventory_png = await self.things.render_inventory(
            result.group,
            captured_at=result.snapshot.captured_at,
            title=title,
        )
        diff_png = None
        if has_item_changes(result.diff):
            diff_png = await self.things.render_diff(result.diff, title=f"{title}变动")
        for res in await self.replies.build_my_things(event, inventory_png, diff_png):
            yield res
