import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from astrbot_plugin_bqyx.errors import BotError
from astrbot_plugin_bqyx.handlers.bind import (
    BindHandlers,
    pick_member_for_uid,
)


def test_pick_member_for_uid_single_match():
    members = [
        SimpleNamespace(uid="111", index=0),
        SimpleNamespace(uid="222", index=4),
    ]
    member = pick_member_for_uid(members, "222")
    assert member is not None
    assert member.index == 4


def test_pick_member_for_uid_missing():
    members = [SimpleNamespace(uid="111", index=0)]
    assert pick_member_for_uid(members, "999") is None


def test_pick_member_for_uid_multiple_archives():
    members = [
        SimpleNamespace(uid="222", index=1),
        SimpleNamespace(uid="222", index=4),
    ]
    with pytest.raises(BotError, match="多个存档"):
        pick_member_for_uid(members, "222")


class FakeEvent:
    def __init__(self, group_id: str = "1001", user_id: str = "456", message: str = ""):
        self.gid = str(group_id)
        self.uid = str(user_id)
        self.message_str = message
        self.replies: list[str] = []

    def get_group_id(self) -> str:
        return self.gid

    def get_sender_id(self) -> str:
        return self.uid

    def plain_result(self, text: str):
        return SimpleNamespace(type="plain", text=text)

    async def reply(self, text: str) -> None:
        self.replies.append(text)

    async def send(self, chain) -> None:
        msg = ""
        for comp in getattr(chain, "chain", []):
            if hasattr(comp, "text"):
                msg += comp.text
        self.replies.append(msg or str(chain))


class DummyBindService(BindHandlers):
    def __init__(self, members):
        from pathlib import Path
        from astrbot_plugin_bqyx.reply import ReplyService

        self.store = MagicMock()
        self.store.set_user_bind = AsyncMock()
        self.store.get_group_army = AsyncMock(return_value=1001)
        self.user = MagicMock()
        self.user.get_members = AsyncMock(return_value=members)
        self.account = MagicMock()
        self.account.get_user = AsyncMock(return_value=self.user)
        self.replies = ReplyService(Path("."))

    async def require_army(self, group_id: str):
        return self.user, 1001


async def invoke_handler(fn, *args, **kwargs):
    try:
        res = fn(*args, **kwargs)
        if hasattr(res, "__anext__"):
            items = []
            async for item in res:
                items.append(item)
            return items
        return await res
    except BotError as err:
        from astrbot_plugin_bqyx.hooks import format_error_markdown
        return [SimpleNamespace(text=format_error_markdown(err))]


@pytest.mark.asyncio
async def test_bind_game_name_empty():
    handler = DummyBindService([])
    event = FakeEvent(group_id="1001", user_id="456", message="绑定游戏名")

    fn = handler.bind_game_name
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    results = await invoke_handler(fn, handler, event, name="")
    assert len(results) == 1
    assert "请输入要绑定的游戏角色名" in getattr(results[0], "text", str(results[0]))


@pytest.mark.asyncio
async def test_bind_game_name_no_match():
    members = [
        SimpleNamespace(
            uid="123456",
            index=0,
            detail=SimpleNamespace(playerName="逍遥剑仙"),
            contribution=1000,
        )
    ]
    handler = DummyBindService(members)
    event = FakeEvent(group_id="1002", user_id="456", message="绑定游戏名 暴龙")

    fn = handler.bind_game_name
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    results = await invoke_handler(fn, handler, event, name="暴龙")
    assert len(results) == 1
    assert "未在本群军队中找到包含" in getattr(results[0], "text", str(results[0]))


@pytest.mark.asyncio
async def test_bind_account_empty():
    handler = DummyBindService([])
    event = FakeEvent(group_id="1001", user_id="456", message="绑定账号")
    results = [res async for res in handler.bind_account(event, username="")]
    assert len(results) == 1
    assert "请输入 4399 账号名" in getattr(results[0], "text", str(results[0]))


@pytest.mark.asyncio
async def test_bind_uid_empty():
    handler = DummyBindService([])
    event = FakeEvent(group_id="1001", user_id="456", message="绑定uid")
    results = [res async for res in handler.bind_uid(event, uid="")]
    assert len(results) == 1
    assert "请提供有效的游戏 UID" in getattr(results[0], "text", str(results[0]))


@pytest.mark.asyncio
async def test_bind_game_name_unique_match_no_uid_exposure():
    members = [
        SimpleNamespace(
            uid="999888777",
            index=0,
            detail=SimpleNamespace(playerName="逍遥剑仙"),
            contribution=50000,
        ),
        SimpleNamespace(
            uid="111222333",
            index=1,
            detail=SimpleNamespace(playerName="无敌暴龙战士"),
            contribution=3000,
        ),
    ]
    handler = DummyBindService(members)
    event = FakeEvent(group_id="1003", user_id="456", message="绑定游戏名 暴龙")

    fn = handler.bind_game_name
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    results = await invoke_handler(fn, handler, event, name="暴龙")

    handler.store.set_user_bind.assert_awaited_once_with(
        "1003", "456", "111222333", 1
    )

    assert len(results) == 1
    reply_text = getattr(results[0], "text", str(results[0]))
    assert "无敌暴龙战士" in reply_text
    assert "999888777" not in reply_text
    assert "111222333" not in reply_text


@pytest.mark.asyncio
async def test_bind_game_name_multi_match_session_select():
    members = [
        SimpleNamespace(
            uid="1001",
            index=0,
            detail=SimpleNamespace(playerName="剑仙李白"),
            contribution=120000,
        ),
        SimpleNamespace(
            uid="1002",
            index=1,
            detail=SimpleNamespace(playerName="逍遥剑仙"),
            contribution=50000,
        ),
    ]
    handler = DummyBindService(members)
    event = FakeEvent(group_id="1004", user_id="456", message="绑定游戏名 剑仙")

    handler.wait_session_reply = AsyncMock(
        return_value=SimpleNamespace(
            ok=True, text="2", timed_out=False, cancelled=False
        )
    )

    fn = handler.bind_game_name
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    results = await invoke_handler(fn, handler, event, name="剑仙")

    assert len(results) == 2
    prompt_text = getattr(results[0], "text", str(results[0]))
    assert '<qqbot-cmd-input text="1" show="剑仙李白" reference="false" /> (总贡献: 120,000)' in prompt_text
    assert '<qqbot-cmd-input text="2" show="逍遥剑仙" reference="false" /> (总贡献: 50,000)' in prompt_text
    assert "1001" not in prompt_text
    assert "1002" not in prompt_text

    handler.store.set_user_bind.assert_awaited_once_with(
        "1004", "456", "1002", 1
    )
    success_text = getattr(results[1], "text", str(results[1]))
    assert "逍遥剑仙" in success_text
    assert "1002" not in success_text


@pytest.mark.asyncio
async def test_bind_game_name_multi_match_session_timeout():
    members = [
        SimpleNamespace(
            uid="1001",
            index=0,
            detail=SimpleNamespace(playerName="剑仙李白"),
            contribution=120000,
        ),
        SimpleNamespace(
            uid="1002",
            index=1,
            detail=SimpleNamespace(playerName="逍遥剑仙"),
            contribution=50000,
        ),
    ]
    handler = DummyBindService(members)
    event = FakeEvent(group_id="1005", user_id="456")

    handler.wait_session_reply = AsyncMock(
        return_value=SimpleNamespace(ok=False, timed_out=True, cancelled=False)
    )

    fn = handler.bind_game_name
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    results = await invoke_handler(fn, handler, event, name="剑仙")
    assert len(results) == 2
    timeout_msg = getattr(results[1], "text", str(results[1]))
    assert "等待超时" in timeout_msg
    handler.store.set_user_bind.assert_not_called()


@pytest.mark.asyncio
async def test_bind_game_name_multi_match_session_cancelled():
    members = [
        SimpleNamespace(
            uid="1001",
            index=0,
            detail=SimpleNamespace(playerName="剑仙李白"),
            contribution=120000,
        ),
        SimpleNamespace(
            uid="1002",
            index=1,
            detail=SimpleNamespace(playerName="逍遥剑仙"),
            contribution=50000,
        ),
    ]
    handler = DummyBindService(members)
    event = FakeEvent(group_id="1006", user_id="456")

    handler.wait_session_reply = AsyncMock(
        return_value=SimpleNamespace(ok=False, timed_out=False, cancelled=True)
    )

    fn = handler.bind_game_name
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    results = await invoke_handler(fn, handler, event, name="剑仙")
    assert len(results) == 2
    cancel_msg = getattr(results[1], "text", str(results[1]))
    assert "已取消绑定" in cancel_msg
    handler.store.set_user_bind.assert_not_called()


@pytest.mark.asyncio
async def test_bind_game_name_multi_match_invalid_index():
    members = [
        SimpleNamespace(
            uid="1001",
            index=0,
            detail=SimpleNamespace(playerName="剑仙李白"),
            contribution=120000,
        ),
        SimpleNamespace(
            uid="1002",
            index=1,
            detail=SimpleNamespace(playerName="逍遥剑仙"),
            contribution=50000,
        ),
    ]
    handler = DummyBindService(members)
    event = FakeEvent(group_id="1007", user_id="456")

    handler.wait_session_reply = AsyncMock(
        return_value=SimpleNamespace(
            ok=True, text="99", timed_out=False, cancelled=False
        )
    )

    fn = handler.bind_game_name
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    results = await invoke_handler(fn, handler, event, name="剑仙")
    assert len(results) == 2
    invalid_msg = getattr(results[1], "text", str(results[1]))
    assert "输入无效序号" in invalid_msg
    handler.store.set_user_bind.assert_not_called()


def test_clean_reply_text():
    from astrbot_plugin_bqyx.context import clean_reply_text

    assert clean_reply_text("[At:qq_official] 99") == "99"
    assert clean_reply_text("[At:qq_official] 取消") == "取消"
    assert clean_reply_text("[At:123456] 1") == "1"
    assert clean_reply_text("@机器人 1") == "1"
    assert clean_reply_text(" /2 ") == "2"
    assert clean_reply_text("#3") == "3"
    assert clean_reply_text("") == ""


@pytest.mark.asyncio
async def test_wait_session_reply_with_pending_handler():
    from astrbot_plugin_bqyx.context import BqyxServices

    service = BqyxServices()
    init_event = FakeEvent(group_id="group_1", user_id="user_1", message="绑定游戏名 杀")

    async def simulate_reply():
        await asyncio.sleep(0.02)
        reply_event = FakeEvent(group_id="group_1", user_id="user_1", message="[At:qq_official] 2")
        reply_event.stop_event = MagicMock()
        await DummyBindService([]).handle_pending_session_reply(reply_event)
        assert reply_event.stop_event.called

    task = asyncio.create_task(simulate_reply())
    res = await service.wait_session_reply(init_event, timeout=1)
    await task

    assert res.ok is True
    assert res.text == "2"
    assert res.cancelled is False
    assert res.timed_out is False


@pytest.mark.asyncio
async def test_wait_session_reply_cancel_with_pending_handler():
    from astrbot_plugin_bqyx.context import BqyxServices

    service = BqyxServices()
    init_event = FakeEvent(group_id="group_2", user_id="user_2", message="绑定游戏名 杀")

    async def simulate_cancel():
        await asyncio.sleep(0.02)
        reply_event = FakeEvent(group_id="group_2", user_id="user_2", message="[At:qq_official] 取消")
        reply_event.stop_event = MagicMock()
        await DummyBindService([]).handle_pending_session_reply(reply_event)
        assert reply_event.stop_event.called

    task = asyncio.create_task(simulate_cancel())
    res = await service.wait_session_reply(init_event, timeout=1)
    await task

    assert res.ok is False
    assert res.cancelled is True


