from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment
from sentence_transformers import SentenceTransformer

from .models import GameMember, QQMember

AUTO_BIND_THRESHOLD = 0.84
SEMANTIC_THRESHOLD = 0.85
SEMANTIC_CANDIDATE_THRESHOLD = 0.70

_GUILD_TAG_PREFIX = re.compile(r"^[a-z][\s·•.、:：|_-]+", re.IGNORECASE)


def normalize_bind_name(name: str) -> str:
    if not name:
        return ""
    name = unicodedata.normalize("NFKC", name).strip().lower()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", name)


def strip_digits(name: str) -> str:
    if not name:
        return ""
    return re.sub(r"\d+", "", name)


def _name_variants(name: str) -> tuple[str, ...]:
    """标准名及去除军团前缀（如 ``D·``）后的名称。"""
    normalized = unicodedata.normalize("NFKC", name or "").strip()
    variants = [normalize_bind_name(normalized)]
    without_tag = _GUILD_TAG_PREFIX.sub("", normalized)
    if without_tag != normalized:
        variants.append(normalize_bind_name(without_tag))
    return tuple(variant for variant in dict.fromkeys(variants) if variant)


@lru_cache(maxsize=1)
def _get_semantic_model() -> SentenceTransformer:
    """延迟加载，避免机器人启动时下载/加载模型。"""
    return SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")


def score_bind_match(qq_name: str, game_name: str) -> tuple[float, str]:
    qq_variants = _name_variants(qq_name)
    game_variants = _name_variants(game_name)
    if not qq_variants or not game_variants:
        return 0.0, "empty"

    if qq_variants[0] == game_variants[0]:
        return 1.0, "exact"

    best_score = 0.0
    best_reason = "low_similarity"
    for qq_norm in qq_variants:
        for game_norm in game_variants:
            if qq_norm == game_norm:
                return 0.99, "exact_without_guild_tag"

            qq_no_digits = strip_digits(qq_norm)
            game_no_digits = strip_digits(game_norm)
            shorter_len = min(len(qq_no_digits), len(game_no_digits))
            if shorter_len >= 3 and qq_no_digits == game_no_digits:
                best_score, best_reason = max(
                    (best_score, best_reason), (0.97, "exact_without_digits")
                )
                continue
            if shorter_len >= 3 and (
                qq_no_digits in game_no_digits or game_no_digits in qq_no_digits
            ):
                best_score, best_reason = max(
                    (best_score, best_reason), (0.93, "contains")
                )
                continue

            # 单字/仅剩军团前缀的 partial ratio 会产生 100 分的假阳性，
            # 因此短名只允许精确匹配，不参与模糊匹配。
            if shorter_len < 3:
                continue

            base_qq = qq_no_digits or qq_norm
            base_game = game_no_digits or game_norm
            ratio = fuzz.ratio(base_qq, base_game) / 100
            partial = fuzz.partial_ratio(base_qq, base_game) / 100
            token = fuzz.token_sort_ratio(base_qq, base_game) / 100
            score = max(ratio, partial * 0.96, token * 0.98)
            if score > best_score:
                best_score = score
                best_reason = "similarity"

    return best_score, best_reason


def _semantic_score_matrix(
    qq_members: list[QQMember], game_members: list[GameMember]
) -> np.ndarray:
    """批量计算昵称余弦相似度，避免在两两循环中反复加载/推理模型。"""
    names = [member.nickname for member in qq_members] + [
        member.nickname for member in game_members
    ]
    embeddings = _get_semantic_model().encode(
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

    semantic_scores = _semantic_score_matrix(qq_candidates, game_candidates)
    score_matrix = [row.copy() for row in lexical_scores]
    for game_idx, game in enumerate(game_candidates):
        for qq_idx, qq in enumerate(qq_candidates):
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
