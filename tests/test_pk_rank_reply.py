from types import SimpleNamespace

from bqyx_api.archive.union import UnionPKRankAgent
from bqyx_bot.reply import _pk_rank_text


def _member(uid: str, name: str, dps: float = 100, score: float = 0) -> SimpleNamespace:
    return SimpleNamespace(
        uid=uid,
        index=0,
        nickname=name,
        contribution=1,
        detail=SimpleNamespace(dps=dps, pkS=score, pkW=0, playerName=name),
    )


def test_pk_rank_text_marks_bound_uid():
    agent = UnionPKRankAgent.from_members(
        [_member("100", "Alice"), _member("200", "Bob")],
        week_index=1,
    )
    text = _pk_rank_text(agent, uid="200")
    assert "军队PK排行" in text
    assert "Alice" in text
    assert "Bob" in text
    bob_line = next(line for line in text.splitlines() if "Bob" in line)
    assert bob_line.endswith(" *")
    alice_line = next(line for line in text.splitlines() if "Alice" in line)
    assert not alice_line.endswith(" *")
