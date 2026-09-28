from __future__ import annotations

from astrbot.api.event import AstrMessageEvent, filter

from ..context import BqyxServices
from ..errors import BotError, GroupOnlyError, ParamError
from ..hooks import command_rate_limit, error_reply
from ..parsing import extract_at
from ..reply import md_cmd_input


class ExcludeHandlers(BqyxServices):
    @error_reply
    @command_rate_limit(name="免at添加")
    @filter.command("免at添加")
    async def add_exclude_at(self, event: AstrMessageEvent, target: str = ""):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        target_at = extract_at(event, target)
        target_qq = target_at.user_id if target_at else target.strip().lstrip("@")
        if not target_qq or not target_qq.isdigit():
            tag = md_cmd_input("/免at添加", "免at添加")
            raise ParamError(
                "请 @ 要添加的群成员或输入 QQ 号",
                usage=f"{tag} @成员 或 {tag} <QQ号>",
            )

        added = await self.store.add_exclude(group_id, target_qq)
        if added:
            yield self.replies.markdown_success(event, f"已将 `{target_qq}` 添加到本群免at名单")
            return
        yield self.replies.markdown_tip(event, f"`{target_qq}` 已在本群免at名单中")

    @error_reply
    @command_rate_limit(name="免at删除")
    @filter.command("免at删除")
    async def remove_exclude_at(
        self, event: AstrMessageEvent, target: str = ""
    ):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        target_at = extract_at(event, target)
        target_qq = target_at.user_id if target_at else target.strip().lstrip("@")
        if not target_qq or not target_qq.isdigit():
            tag = md_cmd_input("/免at删除", "免at删除")
            raise ParamError(
                "请 @ 要移除的群成员或输入 QQ 号",
                usage=f"{tag} @成员 或 {tag} <QQ号>",
            )

        removed = await self.store.remove_exclude(group_id, target_qq)
        if removed:
            yield self.replies.markdown_success(event, f"已将 `{target_qq}` 从本群免at名单移除")
            return
        yield self.replies.markdown_tip(event, f"`{target_qq}` 不在本群免at名单中")

    @error_reply
    @command_rate_limit(name="免at列表")
    @filter.command("免at列表")
    async def list_exclude_at(self, event: AstrMessageEvent):
        group_id = str(event.get_group_id() or "")
        if not group_id:
            raise GroupOnlyError()

        exclude_list = await self.store.list_exclude(group_id)
        if not exclude_list:
            yield self.replies.markdown_tip(event, "本群免at名单为空")
            return
        details = "\n".join(f"- `{qq}`" for qq in exclude_list)
        yield self.replies.markdown_tip(
            event,
            "本群免at名单",
            details,
        )
