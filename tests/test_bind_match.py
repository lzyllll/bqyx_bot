import pytest
from bqyx_bot import bind_match
from bqyx_bot.bind_match import match_members, score_bind_match
from bqyx_bot.models import GameMember, QQMember


@pytest.fixture(autouse=True)
def disable_optional_semantic_model(monkeypatch):
    """默认安装没有 semantic-bind extra 时，应走 LSA 文本匹配。"""
    monkeypatch.setattr(bind_match, "_get_semantic_model", lambda: None)


def test_exact_name_match_binds_uid_and_index():
    qq_members = [QQMember(qq_id="11", nickname="张三")]
    game_members = [GameMember(uid="1001", arch_index=2, nickname="张三")]
    resolved, lines, unmatched = match_members(qq_members, game_members)
    assert resolved == {"11": ("1001", 2)}
    assert unmatched == []
    assert lines


def test_low_similarity_is_not_bound():
    qq_members = [QQMember(qq_id="11", nickname="abcdef")]
    game_members = [GameMember(uid="1001", arch_index=2, nickname="xyz")]
    resolved, _, unmatched = match_members(qq_members, game_members)
    assert resolved == {}
    assert unmatched == ["xyz"]


def test_score_exact():
    score, reason = score_bind_match("Hello", "hello")
    assert score == 1.0
    assert reason == "exact"


def test_prefix_is_not_removed_from_text_match():
    score, reason = score_bind_match("D·凉杉", "凉杉")
    assert score == 0.0
    assert reason == "low_similarity"
