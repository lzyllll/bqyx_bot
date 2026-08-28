from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from .models import GameMember, QQMember

AUTO_BIND_THRESHOLD = 0.84
SEMANTIC_THRESHOLD = 0.85
SEMANTIC_CANDIDATE_THRESHOLD = 0.70


def normalize_bind_name(name: str) -> str:
    if not name:
        return ""
    name = unicodedata.normalize("NFKC", name).strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", name)


def strip_digits(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"\d+", "", name)


@lru_cache(maxsize=1)
def _get_semantic_model() -> Any | None:
    """返回可选的语义模型；未安装 extra 时降级为文本匹配。"""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    return SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")


def score_bind_match(qq_name: str, game_name: str) -> tuple[float, str]:
    qq_norm = normalize_bind_name(qq_name)
    game_norm = normalize_bind_name(game_name)
    if not qq_norm or not game_norm:
        return 0.0, "empty"

    if qq_norm == game_norm:
        return 1.0, "exact"

    qq_no_digits = strip_digits(qq_norm)
    game_no_digits = strip_digits(game_norm)
    shorter_len = min(len(qq_no_digits), len(game_no_digits))
    if shorter_len >= 3 and qq_no_digits == game_no_digits:
        return 0.97, "exact_without_digits"
    if shorter_len >= 3 and (
        qq_no_digits in game_no_digits or game_no_digits in qq_no_digits
    ):
        return 0.93, "contains"

    # 单字昵称的 partial ratio 容易出现 100 分假阳性，短名只允许精确匹配。
    if shorter_len < 3:
        return 0.0, "low_similarity"

    base_qq = qq_no_digits or qq_norm
    base_game = game_no_digits or game_norm
    ratio = fuzz.ratio(base_qq, base_game) / 100
    partial = fuzz.partial_ratio(base_qq, base_game) / 100
    token = fuzz.token_sort_ratio(base_qq, base_game) / 100
    score = max(ratio, partial * 0.96, token * 0.98)
    if score >= AUTO_BIND_THRESHOLD:
        return score, "similarity"
    return score, "low_similarity"


def _semantic_score_matrix(
    qq_members: list[QQMember], game_members: list[GameMember]
) -> np.ndarray | None:
    """批量计算昵称余弦相似度；语义 extra 未安装时返回 ``None``。"""
    model = _get_semantic_model()
    if model is None:
        return None

    names = [member.nickname for member in qq_members] + [
        member.nickname for member in game_members
    ]
    embeddings = model.encode(
        names,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    qq_embeddings = embeddings[: len(qq_members)]
    game_embeddings = embeddings[len(qq_members) :]
    return np.clip(game_embeddings @ qq_embeddings.T, -1.0, 1.0)


def match_members(
    qq_members: list[QQMember],
    game_members: list[GameMember],
) -> tuple[dict[str, tuple[str, int]], list[str], list[str]]:
    """Return qq_id -> (uid, arch_index), auto lines, unmatched game names."""
    qq_candidates = [m for m in qq_members if m.nickname]
    game_candidates = [m for m in game_members if m.nickname]
    if not qq_candidates or not game_candidates:
        return {}, [], [m.nickname for m in game_candidates]

    lexical_scores: list[list[float]] = []
    reasons: list[list[str]] = []
    for game in game_candidates:
        row = [score_bind_match(qq.nickname, game.nickname) for qq in qq_candidates]
        lexical_scores.append([score for score, _ in row])
        reasons.append([reason for _, reason in row])

    score_matrix = [row.copy() for row in lexical_scores]
    semantic_scores = _semantic_score_matrix(qq_candidates, game_candidates)
    if semantic_scores is not None:
        for game_idx in range(len(game_candidates)):
            for qq_idx in range(len(qq_candidates)):
                lexical_score = lexical_scores[game_idx][qq_idx]
                semantic_score = float(semantic_scores[game_idx, qq_idx])
                if (
                    lexical_score >= SEMANTIC_CANDIDATE_THRESHOLD
                    and semantic_score >= SEMANTIC_THRESHOLD
                    and semantic_score > score_matrix[game_idx][qq_idx]
                ):
                    score_matrix[game_idx][qq_idx] = semantic_score
                    reasons[game_idx][qq_idx] = "semantic_similarity"
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

        competing_scores = [
            *score_matrix[game_idx][:qq_idx],
            *score_matrix[game_idx][qq_idx + 1 :],
            *(
                score_matrix[row_idx][qq_idx]
                for row_idx in range(len(game_candidates))
                if row_idx != game_idx
            ),
        ]
        if competing_scores and score - max(competing_scores) < 0.04:
            continue

        resolved[qq.qq_id] = (game.uid, game.arch_index)
        matched_game_uids.add(game.uid)
        auto_lines.append(
            f"✓ {game.nickname} -> {qq.nickname} "
            f"({reasons[game_idx][qq_idx]} {score:.0%})"
        )

    unmatched_games = [
        member.nickname
        for member in game_candidates
        if member.uid not in matched_game_uids
    ]
    return resolved, auto_lines, unmatched_games
