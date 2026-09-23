from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from bqyx_bot.errors import BotError
from bqyx_bot.handlers.bind import (
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


class DummyBindService(BindHandlers):
    def __init__(self, members):
        self.store = MagicMock()
        self.store.set_user_bind = AsyncMock()
        self.user = MagicMock()
        self.user.get_members = AsyncMock(return_value=members)

    async def require_army(self, group_id: str):
        return self.user, 1001


@pytest.mark.asyncio
async def test_bind_game_name_empty():
    handler = DummyBindService([])
    event = MagicMock()
    event.group_id = 1001
    event.user_id = 456
    event.message = SimpleNamespace(text="绑定游戏名")
    event.reply = AsyncMock()

    await handler.bind_game_name(event, name="")
    event.reply.assert_awaited_once()
    assert "请输入要绑定的游戏角色名" in event.reply.call_args[0][0]


@pytest.mark.asyncio
async def test_bind_game_name_no_match():
    members = [
        SimpleNamespace(
            uid="1001",
            index=0,
            detail=SimpleNamespace(playerName="逍遥剑仙"),
            contribution=50000,
        )
    ]
    handler = DummyBindService(members)
    event = MagicMock()
    event.group_id = 1002
    event.user_id = 456
    event.message = SimpleNamespace(text="绑定游戏名 暴龙")
    event.reply = AsyncMock()

    await handler.bind_game_name(event, name="暴龙")
    event.reply.assert_awaited_once()
    assert "未在本群军队中找到包含「暴龙」的成员" in event.reply.call_args[0][0]


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
    event = MagicMock()
    event.group_id = 1003
    event.user_id = 456
    event.message = SimpleNamespace(text="绑定游戏名 暴龙")
    event.reply = AsyncMock()

    await handler.bind_game_name(event, name="暴龙")

    handler.store.set_user_bind.assert_awaited_once_with(
        "1003", "456", "111222333", 1
    )

    event.reply.assert_awaited_once()
    reply_text = event.reply.call_args[0][0]
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
    event = MagicMock()
    event.group_id = 1004
    event.user_id = 456
    event.message = SimpleNamespace(text="绑定游戏名 剑仙")
    event.reply = AsyncMock()

    handler.wait_session_reply = AsyncMock(
        return_value=SimpleNamespace(
            ok=True, text="2", timed_out=False, cancelled=False
        )
    )

    await handler.bind_game_name(event, name="剑仙")

    assert event.reply.call_count == 2
    prompt_text = event.reply.call_args_list[0][0][0]
    assert "剑仙李白 (总贡献: 120,000)" in prompt_text
    assert "逍遥剑仙 (总贡献: 50,000)" in prompt_text
    assert "1001" not in prompt_text
    assert "1002" not in prompt_text

    handler.store.set_user_bind.assert_awaited_once_with(
        "1004", "456", "1002", 1
    )
    success_text = event.reply.call_args_list[1][0][0]
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
    event = MagicMock()
    event.group_id = 1005
    event.user_id = 456
    event.reply = AsyncMock()

    handler.wait_session_reply = AsyncMock(
        return_value=SimpleNamespace(ok=False, timed_out=True, cancelled=False)
    )

    await handler.bind_game_name(event, name="剑仙")
    assert event.reply.call_count == 2
    timeout_msg = event.reply.call_args_list[1][0][0]
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
    event = MagicMock()
    event.group_id = 1006
    event.user_id = 456
    event.reply = AsyncMock()

    handler.wait_session_reply = AsyncMock(
        return_value=SimpleNamespace(ok=False, timed_out=False, cancelled=True)
    )

    await handler.bind_game_name(event, name="剑仙")
    assert event.reply.call_count == 2
    cancel_msg = event.reply.call_args_list[1][0][0]
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
    event = MagicMock()
    event.group_id = 1007
    event.user_id = 456
    event.reply = AsyncMock()

    handler.wait_session_reply = AsyncMock(
        return_value=SimpleNamespace(
            ok=True, text="99", timed_out=False, cancelled=False
        )
    )

    await handler.bind_game_name(event, name="剑仙")
    assert event.reply.call_count == 2
    invalid_msg = event.reply.call_args_list[1][0][0]
    assert "输入无效序号" in invalid_msg
    handler.store.set_user_bind.assert_not_called()
