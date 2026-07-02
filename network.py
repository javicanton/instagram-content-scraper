"""Aristas de red entre usuarios (menciones y co-comentario) para grafos."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import pandas as pd

MENTION_RE = re.compile(r"@([A-Za-z0-9._]{2,30})")


def _normalize_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def _is_valid_username(username: str) -> bool:
    if not username or len(username) < 2:
        return False
    lowered = username.lower()
    if lowered in {"instagram", "facebook", "meta", "threads"}:
        return False
    return bool(re.match(r"^[a-z0-9._]+$", lowered))


def extract_mentions_from_text(text: str) -> list[str]:
    if not text or pd.isna(text):
        return []
    return [m.lower() for m in MENTION_RE.findall(str(text)) if _is_valid_username(m)]


def build_co_comment_edges(
    comments_df: pd.DataFrame,
    *,
    min_shared_posts: int = 2,
) -> pd.DataFrame:
    """Aristas entre usuarios que comentan en los mismos posts."""
    if comments_df.empty:
        return pd.DataFrame(columns=["source", "target", "edge_type", "weight"])

    post_users: dict[str, set[str]] = defaultdict(set)
    for _, row in comments_df.iterrows():
        author = _normalize_username(str(row.get("author_username", "") or ""))
        post_id = str(row.get("post_id", "") or "")
        if _is_valid_username(author) and post_id:
            post_users[post_id].add(author)

    pair_counts: Counter[tuple[str, str]] = Counter()
    for users in post_users.values():
        sorted_users = sorted(users)
        for i, user_a in enumerate(sorted_users):
            for user_b in sorted_users[i + 1 :]:
                pair_counts[(user_a, user_b)] += 1

    rows = []
    for (user_a, user_b), weight in pair_counts.items():
        if weight >= min_shared_posts:
            rows.append(
                {
                    "source": user_a,
                    "target": user_b,
                    "edge_type": "co_comment",
                    "weight": weight,
                }
            )

    return pd.DataFrame(rows)


def build_mention_edges(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
) -> pd.DataFrame:
    """Aristas autor → usuario mencionado."""
    if posts_df.empty and comments_df.empty:
        return pd.DataFrame(columns=["source", "target", "edge_type", "weight"])

    weights: Counter[tuple[str, str, str]] = Counter()

    if not posts_df.empty:
        for _, row in posts_df.iterrows():
            author = _normalize_username(str(row.get("profile_username", "") or ""))
            if not _is_valid_username(author):
                continue
            caption = str(row.get("caption", "") or "")
            for mentioned in extract_mentions_from_text(caption):
                weights[(author, mentioned, "mention_post")] += 1

    if not comments_df.empty:
        for _, row in comments_df.iterrows():
            author = _normalize_username(str(row.get("author_username", "") or ""))
            if not _is_valid_username(author):
                continue
            text = str(row.get("comment_text", "") or "")
            for mentioned in extract_mentions_from_text(text):
                weights[(author, mentioned, "mention_comment")] += 1

    rows = [
        {"source": s, "target": t, "edge_type": et, "weight": w}
        for (s, t, et), w in weights.items()
    ]
    return pd.DataFrame(rows)
