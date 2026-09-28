from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from bqyx_api.archive.things.diff import ItemDelta, ThingsDiff
from astrbot_plugin_bqyx.handlers.things import has_item_changes
from astrbot_plugin_bqyx.reply import ReplyService


def test_has_item_changes_requires_real_delta():
    assert has_item_changes(None) is False
    assert has_item_changes(ThingsDiff()) is False
    assert has_item_changes(
        ThingsDiff(added=[ItemDelta(name="lifeBottle", cn_name="生命药瓶", after=1)])
    ) is True


@pytest.mark.asyncio
async def test_send_my_things_without_diff(tmp_path):
    replies = ReplyService(workspace=tmp_path)
    event = MagicMock()
    event.get_self_id.return_value = "12345"

    results = await replies.build_my_things(event, b"inventory-bytes")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_send_my_things_with_diff(tmp_path):
    replies = ReplyService(workspace=tmp_path)
    event = MagicMock()
    event.get_self_id.return_value = "12345"

    results = await replies.build_my_things(event, b"inventory-bytes", b"diff-bytes")
    assert len(results) == 2
