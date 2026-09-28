from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from astrbot_plugin_bqyx.reply import ReplyService


@pytest.mark.asyncio
async def test_send_role_dps_report_without_arms(tmp_path):
    replies = ReplyService(workspace=tmp_path, bot_id="99999")
    event = MagicMock()
    event.get_self_id.return_value = "99999"

    results = await replies.build_role_dps_report(
        event,
        panel_png=b"panel-bytes",
        bonus_prop_png=b"prop-bytes",
        bonus_mod_png=b"mod-bytes",
        title="玩家A 的战力",
    )
    assert len(results) == 4


@pytest.mark.asyncio
async def test_send_role_dps_report_with_arms(tmp_path):
    replies = ReplyService(workspace=tmp_path, bot_id="99999")
    event = MagicMock()
    event.get_self_id.return_value = "99999"

    results = await replies.build_role_dps_report(
        event,
        panel_png=b"panel-bytes",
        bonus_prop_png=b"prop-bytes",
        bonus_mod_png=b"mod-bytes",
        arms_png=b"arms-bytes",
        title="玩家A 的战力",
    )
    assert len(results) == 5
