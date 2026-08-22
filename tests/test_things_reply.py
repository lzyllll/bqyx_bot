from types import SimpleNamespace

from bqyx_api.archive.things.diff import ItemDelta, ThingsDiff
from bqyx_bot.handlers.things import has_item_changes
from bqyx_bot.reply import ReplyService


def test_has_item_changes_requires_real_delta():
    assert has_item_changes(None) is False
    assert has_item_changes(ThingsDiff()) is False
    assert has_item_changes(
        ThingsDiff(added=[ItemDelta(name="lifeBottle", cn_name="生命药瓶", after=1)])
    ) is True


def test_things_forward_only_inventory(tmp_path):
    replies = ReplyService(api=None, workspace=tmp_path)
    event = SimpleNamespace(self_id="1", group_id="2")
    forward = replies.build_things_forward(event, b"inventory-bytes")
    assert len(forward.content) == 1


def test_things_forward_appends_diff_image(tmp_path):
    replies = ReplyService(api=None, workspace=tmp_path)
    event = SimpleNamespace(self_id="1", group_id="2")
    forward = replies.build_things_forward(event, b"inventory-bytes", b"diff-bytes")
    assert len(forward.content) == 2
