from types import SimpleNamespace

import pytest

from bqyx_bot.errors import BotError
from bqyx_bot.handlers.bind import pick_member_for_uid


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
