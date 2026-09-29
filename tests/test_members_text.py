import urllib.parse
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from astrbot_plugin_bqyx.handlers.query import QueryHandlers
from astrbot_plugin_bqyx.models import ContributionKind
from astrbot_plugin_bqyx.reply import ReplyService
from astrbot_plugin_bqyx.store import SqliteStore
from pathlib import Path


class FakeEvent:
    def __init__(self, message_str: str, group_id: str = "group_1", sender_id: str = "qq_1"):
        self.message_str = message_str
        self.gid = group_id
        self.sid = sender_id

    def get_group_id(self):
        return self.gid

    def get_sender_id(self):
        return self.sid

    def plain_result(self, text: str):
        return SimpleNamespace(type="plain", text=text)


@pytest.mark.asyncio
async def test_check_members_text_format(tmp_path):
    store = SqliteStore(tmp_path / "test_m_text.db")
    await store.init()
    await store.set_group_army("group_1", 101)

    mock_user = AsyncMock()
    mock_members = [
        SimpleNamespace(
            uid="uid_1",
            index=0,
            detail=SimpleNamespace(playerName="剑仙李白", conDay=1200, vip=0, money=0),
            contribution=100000,
        ),
        SimpleNamespace(
            uid="uid_2",
            index=1,
            detail=SimpleNamespace(playerName="逍遥剑仙", conDay=600, vip=1, money=100),
            contribution=50000,
        ),
    ]
    # 支持 sort 方法
    class MemberCollection(list):
        def sort(self, key=None, reverse=False):
            return MemberCollection(sorted(self, key=key, reverse=reverse))

    mock_user.get_members.return_value = MemberCollection(mock_members)

    mock_account_service = AsyncMock()
    mock_account_service.get_user.return_value = mock_user

    handlers = QueryHandlers()
    handlers.store = store
    handlers.account = mock_account_service
    handlers.replies = ReplyService(Path("."))

    fn = handlers.check_members
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    event = FakeEvent("查成员")  # 默认应为文本
    results = []
    res = fn(handlers, event)
    if hasattr(res, "__anext__"):
        async for r in res:
            results.append(r)
    else:
        results.append(await res)

    assert len(results) == 1
    reply_text = getattr(results[0], "text", str(results[0]))

    # 验证 markdown_tip 格式
    assert "> 💡 **军团成员列表 (共 2 人)**" in reply_text
    # 验证可交互点击标签：查贡献
    encoded_cmd1 = urllib.parse.quote("查贡献 剑仙李白")
    assert f'<qqbot-cmd-input text="{encoded_cmd1}" show="剑仙李白" reference="false" />' in reply_text
    encoded_cmd2 = urllib.parse.quote("查贡献 逍遥剑仙")
    assert f'<qqbot-cmd-input text="{encoded_cmd2}" show="逍遥剑仙" reference="false" />' in reply_text
    assert "点击角色名可直接调用 查贡献" in reply_text

    # 验证在 tip 外部追加红色的“查成员 图片”调用标签，不要放在 tip (>) 里
    encoded_img_cmd = urllib.parse.quote("查成员 图片")
    red_link = f'<qqbot-cmd-input text="{encoded_img_cmd}" show="🔴 查成员 图片" reference="false" />'
    assert f"\n\n{red_link}" in reply_text
    assert f"> {red_link}" not in reply_text


@pytest.mark.asyncio
async def test_check_daily_contribution_text_format(tmp_path):
    store = SqliteStore(tmp_path / "test_daily_text.db")
    await store.init()
    await store.set_group_army("group_1", 101)

    mock_user = AsyncMock()
    mock_members = [
        SimpleNamespace(
            uid="uid_1",
            detail=SimpleNamespace(playerName="偷懒玩家", conDay=20),
            contribution=1000,
        ),
    ]

    class MemberCollection(list):
        def filter(self, predicate):
            return MemberCollection([m for m in self if predicate(m)])

        def sort(self, key=None, reverse=False):
            return MemberCollection(sorted(self, key=key, reverse=reverse))

    mock_user.get_members.return_value = MemberCollection(mock_members)

    mock_account_service = AsyncMock()
    mock_account_service.get_user.return_value = mock_user

    handlers = QueryHandlers()
    handlers.store = store
    handlers.account = mock_account_service
    handlers.replies = ReplyService(Path("."))

    fn = handlers.check_daily_contribution
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    event = FakeEvent("查日贡 文本 100")
    results = []
    res = fn(handlers, event)
    if hasattr(res, "__anext__"):
        async for r in res:
            results.append(r)
    else:
        results.append(await res)

    assert len(results) == 1
    reply_text = getattr(results[0], "text", str(results[0]))

    # 验证 markdown_tip 格式及点击标签
    assert "> 💡 **以下成员今日贡献低于 100 (共 1 人)：**" in reply_text
    encoded_cmd = urllib.parse.quote("查贡献 偷懒玩家")
    assert f'<qqbot-cmd-input text="{encoded_cmd}" show="偷懒玩家" reference="false" />' in reply_text
    assert "点击角色名可直接调用 查贡献" in reply_text

    # 验证在 tip 外部追加红色的“查日贡 图片 100”调用标签，不在 tip (>) 里
    encoded_img_cmd = urllib.parse.quote("查日贡 图片 100")
    red_link = f'<qqbot-cmd-input text="{encoded_img_cmd}" show="🔴 查日贡 图片 100" reference="false" />'
    assert f"\n\n{red_link}" in reply_text
    assert f"> {red_link}" not in reply_text


@pytest.mark.asyncio
async def test_check_members_sorting(tmp_path):
    """查成员时：先按总贡献降序，再按日贡献降序。"""
    store = SqliteStore(tmp_path / "test_sort_m.db")
    await store.init()
    await store.set_group_army("group_1", 101)

    mock_user = AsyncMock()
    m_low_total_high_day = SimpleNamespace(
        uid="u1", detail=SimpleNamespace(playerName="玩家1", conDay=1400, vip=0, money=0), contribution=50000
    )
    m_high_total_low_day = SimpleNamespace(
        uid="u2", detail=SimpleNamespace(playerName="玩家2", conDay=100, vip=0, money=0), contribution=100000
    )
    m_high_total_high_day = SimpleNamespace(
        uid="u3", detail=SimpleNamespace(playerName="玩家3", conDay=1400, vip=0, money=0), contribution=100000
    )

    class MemberCollection(list):
        def sort(self, key=None, reverse=False):
            return MemberCollection(sorted(self, key=key, reverse=reverse))

    mock_user.get_members.return_value = MemberCollection([
        m_low_total_high_day,
        m_high_total_low_day,
        m_high_total_high_day,
    ])
    mock_account = AsyncMock()
    mock_account.get_user.return_value = mock_user

    captured_members = None

    class FakeReplies:
        async def build_members(self, event, members, *args, **kwargs):
            nonlocal captured_members
            captured_members = list(members)
            return [SimpleNamespace(text="ok")]

    handlers = QueryHandlers()
    handlers.store = store
    handlers.account = mock_account
    handlers.replies = FakeReplies()

    fn = handlers.check_members
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    res = fn(handlers, FakeEvent("查成员"))
    if hasattr(res, "__anext__"):
        async for _ in res:
            pass
    else:
        await res

    assert captured_members is not None
    # 期望顺序：
    # 1. 玩家3: 总贡献 100000, 日贡 1400
    # 2. 玩家2: 总贡献 100000, 日贡 100
    # 3. 玩家1: 总贡献 50000, 日贡 1400
    assert [m.uid for m in captured_members] == ["u3", "u2", "u1"]


@pytest.mark.asyncio
async def test_check_daily_contribution_sorting(tmp_path):
    """查日贡时：按日贡献降序排序。"""
    store = SqliteStore(tmp_path / "test_sort_d.db")
    await store.init()
    await store.set_group_army("group_1", 101)

    mock_user = AsyncMock()
    m1 = SimpleNamespace(
        uid="u1", detail=SimpleNamespace(playerName="玩家1", conDay=200, conObj=SimpleNamespace(this_week=1000)), contribution=10000
    )
    m2 = SimpleNamespace(
        uid="u2", detail=SimpleNamespace(playerName="玩家2", conDay=800, conObj=SimpleNamespace(this_week=2000)), contribution=5000
    )
    m3 = SimpleNamespace(
        uid="u3", detail=SimpleNamespace(playerName="玩家3", conDay=0, conObj=SimpleNamespace(this_week=500)), contribution=20000
    )

    class MemberCollection(list):
        def filter(self, predicate):
            return MemberCollection([m for m in self if predicate(m)])
        def sort(self, key=None, reverse=False):
            return MemberCollection(sorted(self, key=key, reverse=reverse))

    mock_user.get_members.return_value = MemberCollection([m1, m2, m3])
    mock_account = AsyncMock()
    mock_account.get_user.return_value = mock_user

    captured_members = None

    class FakeReplies:
        async def build_members(self, event, members, *args, **kwargs):
            nonlocal captured_members
            captured_members = list(members)
            return [SimpleNamespace(text="ok")]

    handlers = QueryHandlers()
    handlers.store = store
    handlers.account = mock_account
    handlers.replies = FakeReplies()

    fn = handlers.check_daily_contribution
    while hasattr(fn, "__wrapped__"):
        fn = fn.__wrapped__

    res = fn(handlers, FakeEvent("查日贡 1000"))
    if hasattr(res, "__anext__"):
        async for _ in res:
            pass
    else:
        await res

    assert captured_members is not None
    # 期望顺序（按 conDay 降序：800 -> 200 -> 0）：
    assert [m.uid for m in captured_members] == ["u2", "u1", "u3"]

