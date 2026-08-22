from __future__ import annotations

import re

from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from .models import GameMember, QQMember

AUTO_BIND_THRESHOLD = 0.84


def normalize_bind_name(name: str) -> str:
    if not name:
        return ""
    name = name.strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", name)


def strip_digits(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"\d+", "", name)


def score_bind_match(qq_name: str, game_name: str) -> tuple[float, str]:
    qq_norm = normalize_bind_name(qq_name)
    game_norm = normalize_bind_name(game_name)
    if not qq_norm or not game_norm:
        return 0.0, "empty"

    if qq_norm == game_norm:
        return 1.0, "exact"

    qq_no_digits = strip_digits(qq_norm)
    game_no_digits = strip_digits(game_norm)
    if qq_no_digits and game_no_digits and qq_no_digits == game_no_digits:
        return 0.97, "exact_without_digits"

    shorter_len = min(len(qq_no_digits), len(game_no_digits))
    if shorter_len >= 2 and (
        qq_no_digits in game_no_digits or game_no_digits in qq_no_digits
    ):
        return 0.93, "contains"

    base_qq = qq_no_digits or qq_norm
    base_game = game_no_digits or game_norm
    ratio = fuzz.ratio(base_qq, base_game) / 100
    partial = fuzz.partial_ratio(base_qq, base_game) / 100
    token = fuzz.token_sort_ratio(base_qq, base_game) / 100
    score = max(ratio, partial * 0.96, token * 0.98)

    if score >= 0.92:
        return score, "high_similarity"
    if score >= AUTO_BIND_THRESHOLD:
        return score, "similarity"
    return score, "low_similarity"


def match_members(
    qq_members: list[QQMember],
    game_members: list[GameMember],
) -> tuple[dict[str, tuple[str, int]], list[str], list[str]]:
    """Return qq_id -> (uid, arch_index), auto lines, unmatched game names."""
    qq_candidates = [m for m in qq_members if m.nickname]
    game_candidates = [m for m in game_members if m.nickname]
    if not qq_candidates or not game_candidates:
        return {}, [], [m.nickname for m in game_candidates]

    score_matrix = [
        [score_bind_match(qq.nickname, game.nickname)[0] for qq in qq_candidates]
        for game in game_candidates
    ]
    cost_matrix = [[1 - score for score in row] for row in score_matrix]
    row_indexes, col_indexes = linear_sum_assignment(cost_matrix)

    resolved: dict[str, tuple[str, int]] = {}
    matched_game_uids: set[str] = set()
    auto_lines: list[str] = []

    for game_idx, qq_idx in zip(row_indexes.tolist(), col_indexes.tolist()):
        game = game_candidates[game_idx]
        qq = qq_candidates[qq_idx]
        score = score_matrix[game_idx][qq_idx]
        if score < AUTO_BIND_THRESHOLD:
            continue
        resolved[qq.qq_id] = (game.uid, game.arch_index)
        matched_game_uids.add(game.uid)
        auto_lines.append(f"✓ {game.nickname} -> {qq.nickname}")

    unmatched_games = [
        member.nickname
        for member in game_candidates
        if member.uid not in matched_game_uids
    ]
    return resolved, auto_lines, unmatched_games
