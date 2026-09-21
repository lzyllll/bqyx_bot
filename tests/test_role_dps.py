from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bqyx_bot.errors import BotError, UserNotBoundError
from bqyx_bot.handlers.query import QueryHandlers
from bqyx_bot.hooks import my_dps_limit, total_call_limit
from bqyx_bot.models import UserBind
from bqyx_bot.reply import ReplyService


class FakeEvent:
    def __init__(self, user_id: str = "10001", group_id: str = "20002") -> None:
        self.user_id = user_id
        self.group_id = group_id
        self.self_id = "99999"
        self.replies: list[str] = []

    async def reply(self, text: str) -> None:
        self.replies.append(text)


def test_build_role_dps_forward(tmp_path):
    replies = ReplyService(api=None, workspace=tmp_path, bot_id="99999")
    event = FakeEvent()
    # 无 arms_png: 1 text + 3 images = 4
    forward_without_arms = replies.build_role_dps_forward(
        event,
        panel_png=b"panel-bytes",
        bonus_prop_png=b"prop-bytes",
        bonus_mod_png=b"mod-bytes",
        title="玩家A 的战力",
    )
    assert len(forward_without_arms.content) == 4

    # 有 arms_png: 1 text + 4 images = 5
    forward_with_arms = replies.build_role_dps_forward(
        event,
        panel_png=b"panel-bytes",
        bonus_prop_png=b"prop-bytes",
        bonus_mod_png=b"mod-bytes",
        arms_png=b"arms-bytes",
        title="玩家A 的战力",
    )
    assert len(forward_with_arms.content) == 5


@pytest.mark.asyncio
async def test_my_dps_rate_limit(monkeypatch):
    """我的战力限流：每群限制与独立窗口。"""
    from bqyx_bot.hooks import GroupRateLimiter

    total_call_limit.reset()
    limiter = GroupRateLimiter(max_calls=1, period=30, name="测试战力")
    monkeypatch.setattr("bqyx_bot.hooks.time.monotonic", lambda: 100.0)

    first_event = FakeEvent(group_id="group_1")
    second_event = FakeEvent(group_id="group_2")

    called = []

    @limiter
    async def handler(self, event):
        called.append(event.group_id)
        return "ok"

    plugin = SimpleNamespace(store=None)
    # 第一群第一次：成功
    assert await handler(plugin, first_event) == "ok"
    # 第二群第一次：成功（不同群独立窗口）
    assert await handler(plugin, second_event) == "ok"
    # 第一群 30s 内第二次：被拦截
    assert await handler(plugin, first_event) is None
    assert first_event.replies == ["操作太频繁，请 30 秒后再试。"]

    total_call_limit.reset()


@pytest.mark.asyncio
async def test_check_my_dps_unbound_raises():
    store = AsyncMock()
    store.get_user_bind.return_value = None

    handlers = QueryHandlers()
    handlers.store = store

    event = FakeEvent()
    with pytest.raises(UserNotBoundError):
        # Unwrap error_reply and my_dps_limit to test direct logic
        await handlers.check_my_dps.__wrapped__.__wrapped__(handlers, event)

    # With @target
    target = SimpleNamespace(user_id="88888")
    with pytest.raises(BotError, match="尚未在本群绑定游戏账号"):
        await handlers.check_my_dps.__wrapped__.__wrapped__(handlers, event, target=target)


@pytest.mark.asyncio
async def test_check_my_dps_success_flow():
    bind = UserBind(group_id="20002", qq_id="10001", uid="506106961", arch_index=1)
    store = AsyncMock()
    store.get_user_bind.return_value = bind
    store.get_group_army.return_value = None

    mock_account_data = SimpleNamespace(title="大罗金仙")
    mock_game_user = AsyncMock()
    mock_game_user.get_account.return_value = mock_account_data

    account_service = AsyncMock()
    account_service.get_user.return_value = mock_game_user

    mock_panel_view = SimpleNamespace(player_name="大罗金仙")
    mock_summary = SimpleNamespace()

    player_bonus_mock = MagicMock()
    player_bonus_mock.get_role_panel_and_bonus.return_value = (mock_panel_view, mock_summary)
    player_bonus_mock.get_role_panel_and_bonus_async = AsyncMock(return_value=(mock_panel_view, mock_summary))

    reply_mock = AsyncMock()

    handlers = QueryHandlers()
    handlers.store = store
    handlers.account = account_service
    handlers.replies = reply_mock
    handlers.player_bonus = player_bonus_mock

    event = FakeEvent()

    with (
        patch("bqyx_bot.handlers.query.render_role_panel_image_async", new=AsyncMock(return_value=b"panel_png")),
        patch("bqyx_bot.handlers.query.render_role_bonus_image_async", new=AsyncMock(side_effect=[b"prop_png", b"mod_png"])),
        patch("bqyx_bot.handlers.query.render_role_arms_image_async", new=AsyncMock(return_value=b"arms_png")),
    ):
        await handlers.check_my_dps.__wrapped__.__wrapped__(handlers, event)

    player_bonus_mock.get_role_panel_and_bonus_async.assert_awaited_once()
    reply_mock.send_role_dps_report.assert_awaited_once_with(
        event,
        b"panel_png",
        b"prop_png",
        b"mod_png",
        arms_png=b"arms_png",
        title="大罗金仙 的战力",
    )


@pytest.mark.asyncio
async def test_check_other_user_dps_flow():
    """查战力 @xxx：使用被 @ 用户的 uid 和 arch_index 进行查询。"""
    bind = UserBind(group_id="20002", qq_id="88888", uid="88888888", arch_index=2)
    store = AsyncMock()
    store.get_user_bind.return_value = bind
    store.get_group_army.return_value = None

    mock_account_data = SimpleNamespace(title="道友乙")
    mock_game_user = AsyncMock()
    mock_game_user.get_account.return_value = mock_account_data

    account_service = AsyncMock()
    account_service.get_user.return_value = mock_game_user

    mock_panel_view = SimpleNamespace(player_name="道友乙")
    mock_summary = SimpleNamespace()

    player_bonus_mock = MagicMock()
    player_bonus_mock.get_role_panel_and_bonus.return_value = (mock_panel_view, mock_summary)
    player_bonus_mock.get_role_panel_and_bonus_async = AsyncMock(return_value=(mock_panel_view, mock_summary))

    reply_mock = AsyncMock()

    handlers = QueryHandlers()
    handlers.store = store
    handlers.account = account_service
    handlers.replies = reply_mock
    handlers.player_bonus = player_bonus_mock

    event = FakeEvent(user_id="10001", group_id="20002")
    target = SimpleNamespace(user_id="88888")

    with (
        patch("bqyx_bot.handlers.query.render_role_panel_image_async", new=AsyncMock(return_value=b"panel_png")),
        patch("bqyx_bot.handlers.query.render_role_bonus_image_async", new=AsyncMock(side_effect=[b"prop_png", b"mod_png"])),
        patch("bqyx_bot.handlers.query.render_role_arms_image_async", new=AsyncMock(return_value=b"arms_png")),
    ):
        await handlers.check_my_dps.__wrapped__.__wrapped__(handlers, event, target=target)

    # 确认是用目标用户的 QQ 查询绑定
    store.get_user_bind.assert_awaited_once_with("20002", "88888")
    # 确认是用目标用户的 uid 和 arch_index 获取游戏账号
    mock_game_user.get_account.assert_awaited_once_with("88888888", 2)
    # 确认角色面板与加成计算使用的是目标用户的 uid 与 arch_index
    player_bonus_mock.get_role_panel_and_bonus_async.assert_awaited_once_with(
        mock_account_data,
        uid="88888888",
        archive_index=2,
        union_info=None,
        member_info=None,
        member_list=None,
    )
    reply_mock.send_role_dps_report.assert_awaited_once_with(
        event,
        b"panel_png",
        b"prop_png",
        b"mod_png",
        arms_png=b"arms_png",
        title="道友乙 的战力",
    )


