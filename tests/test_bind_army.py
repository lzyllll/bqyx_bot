from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest

from astrbot_plugin_bqyx.handlers.bind import BindHandlers


class FakeEvent:
    def __init__(self, group_id: str = "1001", user_id: str = "456", message: str = ""):
        self.gid = str(group_id)
        self.uid = str(user_id)
        self.message_str = message

    def get_group_id(self) -> str:
        return self.gid

    def get_sender_id(self) -> str:
        return self.uid

    def plain_result(self, text: str):
        return SimpleNamespace(type="plain", text=text)


class DummyBindArmyService(BindHandlers):
    def __init__(self, union_info=None, raise_exc=None):
        self.store = MagicMock()
        self.store.set_group_army = AsyncMock()
        self.account = MagicMock()
        user = MagicMock()
        if raise_exc:
            user.get_union_info = AsyncMock(side_effect=raise_exc)
        else:
            user.get_union_info = AsyncMock(return_value=union_info)
        self.account.get_user = AsyncMock(return_value=user)


@pytest.mark.asyncio
async def test_bind_army_private_chat():
    handler = DummyBindArmyService()
    event = FakeEvent(group_id="", user_id="456", message="绑定军队 26490")
    results = [res async for res in handler.bind_army(event, army_id="26490")]
    assert len(results) == 1
    assert "仅支持在群聊中使用" in results[0].text
    handler.store.set_group_army.assert_not_called()


@pytest.mark.asyncio
async def test_bind_army_missing_param():
    handler = DummyBindArmyService()
    event = FakeEvent(group_id="1001", user_id="456", message="绑定军队")
    results = [res async for res in handler.bind_army(event, army_id="")]
    assert len(results) == 1
    assert "请输入军队ID" in results[0].text
    handler.store.set_group_army.assert_not_called()


@pytest.mark.asyncio
async def test_bind_army_invalid_digits():
    handler = DummyBindArmyService()
    event = FakeEvent(group_id="1001", user_id="456", message="绑定军队 abc")
    results = [res async for res in handler.bind_army(event, army_id="abc")]
    assert len(results) == 1
    assert "格式错误" in results[0].text
    handler.store.set_group_army.assert_not_called()


@pytest.mark.asyncio
async def test_bind_army_success():
    union = SimpleNamespace(nickname="先锋军团", title=None, union_id=26490)
    handler = DummyBindArmyService(union_info=union)
    event = FakeEvent(group_id="1001", user_id="456", message="绑定军队 26490")
    results = [res async for res in handler.bind_army(event, army_id="26490")]
    assert len(results) == 1
    assert "本群已成功绑定军队: 先锋军团 (26490)" in results[0].text
    handler.store.set_group_army.assert_awaited_once_with("1001", 26490)


@pytest.mark.asyncio
async def test_bind_army_not_found():
    handler = DummyBindArmyService(union_info=None)
    event = FakeEvent(group_id="1001", user_id="456", message="绑定军队 26490")
    results = [res async for res in handler.bind_army(event, army_id="26490")]
    assert len(results) == 1
    assert "未查询到军队 ID 26490 的信息" in results[0].text
    handler.store.set_group_army.assert_not_called()


@pytest.mark.asyncio
async def test_bind_army_api_error():
    handler = DummyBindArmyService(raise_exc=RuntimeError("网络连接超时"))
    event = FakeEvent(group_id="1001", user_id="456", message="绑定军队 26490")
    results = [res async for res in handler.bind_army(event, army_id="26490")]
    assert len(results) == 1
    assert "绑定军队失败" in results[0].text
    assert "网络连接超时" in results[0].text
    handler.store.set_group_army.assert_not_called()
