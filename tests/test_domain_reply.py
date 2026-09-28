from unittest.mock import AsyncMock, MagicMock
import pytest
from astrbot_plugin_bqyx.reply import ReplyService


@pytest.mark.asyncio
async def test_send_domain_image_sync_renderer(tmp_path):
    replies = ReplyService(workspace=tmp_path)
    replies.domain_renderer.image = MagicMock(return_value=b"fake-png-bytes")

    event = MagicMock()
    event.get_self_id.return_value = "12345"

    results = await replies.build_domain(event, [], None, format_type="图片", uid="test_uid")
    replies.domain_renderer.image.assert_called_once_with([], None, uid="test_uid")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_send_domain_image_async_renderer(tmp_path):
    replies = ReplyService(workspace=tmp_path)
    replies.domain_renderer.image = AsyncMock(return_value=b"fake-png-bytes")

    event = MagicMock()
    event.get_self_id.return_value = "12345"

    results = await replies.build_domain(event, [], None, format_type="图片", uid="test_uid")
    replies.domain_renderer.image.assert_awaited_once_with([], None, uid="test_uid")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_send_domain_text(tmp_path):
    replies = ReplyService(workspace=tmp_path)
    replies.domain_renderer.text = MagicMock(return_value="domain text summary")

    event = MagicMock()
    event.get_self_id.return_value = "12345"

    results = await replies.build_domain(event, [], None, format_type="文本", uid="test_uid")
    replies.domain_renderer.text.assert_called_once_with([], None, uid="test_uid")
    assert len(results) == 1
