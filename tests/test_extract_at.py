from types import SimpleNamespace
import pytest
from astrbot.api.message_components import At, Plain

from astrbot_plugin_bqyx.parsing import TargetAt, extract_at


class MockEvent:
    def __init__(self, bot_id="888888", messages=None, message_str="", sender_id="user1"):
        self._self_id = bot_id
        self._messages = messages or []
        self.message_str = message_str
        self._sender_id = sender_id

    def get_self_id(self):
        return self._self_id

    def get_sender_id(self):
        return self._sender_id

    def get_messages(self):
        return self._messages


def test_extract_at_only_bot_returns_none():
    ev = MockEvent("888888", [At(qq=888888), Plain(text=" 我的贡献")], message_str="@Bot 我的贡献")
    result = extract_at(ev, target="")
    assert result is None


def test_extract_at_bot_and_other_user():
    ev = MockEvent(
        "888888",
        [At(qq=888888), Plain(text=" 我的贡献 "), At(qq=123456)],
        message_str="@Bot 我的贡献 @张三",
    )
    result = extract_at(ev, target="")
    assert result is not None
    assert result.user_id == "123456"


def test_extract_at_with_date_param_returns_none():
    ev = MockEvent("888888", [At(qq=888888), Plain(text=" 我的贡献 2026-09")], message_str="@Bot 我的贡献 2026-09")
    result = extract_at(ev, target="2026-09")
    assert result is None


def test_extract_at_with_6digit_yearmonth_param_returns_none():
    ev = MockEvent("888888", [At(qq=888888), Plain(text=" 我的贡献 202609")], message_str="@Bot 我的贡献 202609")
    result = extract_at(ev, target="202609")
    assert result is None


def test_extract_at_target_is_explicit_at():
    ev = MockEvent("888888", [At(qq=888888)], message_str="@Bot 我的贡献 @123456")
    result = extract_at(ev, target="@123456")
    assert result is not None
    assert result.user_id == "123456"


def test_extract_at_target_is_bot_ignored():
    ev = MockEvent("888888", [At(qq=888888)], message_str="@Bot 我的贡献 @Bot")
    result = extract_at(ev, target="@888888")
    assert result is None


def test_extract_at_cq_code_other_user():
    ev = MockEvent("888888", [], message_str="[CQ:at,qq=888888] 我的贡献 [CQ:at,qq=654321]")
    result = extract_at(ev, target="")
    assert result is not None
    assert result.user_id == "654321"


def test_extract_at_qqofficial_default_self_id():
    # qqofficial 未解析到具体 ID 时默认 self_id 为 qq_official
    ev = MockEvent(
        bot_id="qq_official",
        messages=[At(qq="qq_official"), Plain(text=" 我的贡献")],
        message_str="我的贡献",
        sender_id="USER_OPENID_ABC123",
    )
    result = extract_at(ev, target="")
    assert result is None


def test_extract_at_qqofficial_with_month_or_format():
    ev = MockEvent(
        bot_id="qq_official",
        messages=[At(qq="qq_official"), Plain(text=" 我的贡献 2026-09")],
        message_str="我的贡献 2026-09",
        sender_id="USER_OPENID_ABC123",
    )
    assert extract_at(ev, target="2026-09") is None
    assert extract_at(ev, target="上月") is None
    assert extract_at(ev, target="图片") is None
    assert extract_at(ev, target="文本") is None


def test_extract_at_qqofficial_query_other_user():
    ev = MockEvent(
        bot_id="qq_official",
        messages=[
            At(qq="qq_official"),
            Plain(text=" 我的贡献 "),
            At(qq="OTHER_USER_OPENID_456"),
        ],
        message_str="我的贡献 @张三",
        sender_id="USER_OPENID_ABC123",
    )
    result = extract_at(ev, target="")
    assert result is not None
    assert result.user_id == "OTHER_USER_OPENID_456"


def test_extract_at_qqofficial_raw_message_mentions():
    # 模拟包含 raw_message.mentions 的场景
    ev = MockEvent(
        bot_id="",
        messages=[At(qq="BOT_MENTION_ID_789"), Plain(text=" 我的贡献")],
        message_str="我的贡献",
        sender_id="USER_OPENID_ABC123",
    )
    ev.message_obj = SimpleNamespace(
        self_id="BOT_MENTION_ID_789",
        raw_message=SimpleNamespace(
            mentions=[SimpleNamespace(id="BOT_MENTION_ID_789", is_you=True)]
        ),
    )
    result = extract_at(ev, target="")
    assert result is None

