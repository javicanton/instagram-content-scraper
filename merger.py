"""Merge incremental de CSV unificados sin duplicados."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from normalizer import COMMENT_COLUMNS, POST_COLUMNS


def _read_existing(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def _ensure_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def merge_posts(existing_path: Path, new_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    existing = _read_existing(existing_path, POST_COLUMNS)
    new_df = _ensure_columns(new_df.copy(), POST_COLUMNS)

    if existing.empty:
        merged = new_df.drop_duplicates(subset=["post_id"], keep="last")
        return merged, len(merged)

    combined = pd.concat([existing, new_df], ignore_index=True)
    before = len(combined)
    merged = combined.drop_duplicates(subset=["post_id"], keep="last")
    new_count = len(merged) - len(existing)
    if new_count < 0:
        new_count = before - len(merged)
    return merged, max(new_count, 0)


def merge_comments(
    existing_path: Path, new_df: pd.DataFrame
) -> tuple[pd.DataFrame, int]:
    existing = _read_existing(existing_path, COMMENT_COLUMNS)
    new_df = _ensure_columns(new_df.copy(), COMMENT_COLUMNS)

    if existing.empty:
        merged = new_df.drop_duplicates(subset=["comment_id"], keep="last")
        return merged, len(merged)

    combined = pd.concat([existing, new_df], ignore_index=True)
    before = len(combined)
    merged = combined.drop_duplicates(subset=["comment_id"], keep="last")
    new_count = len(merged) - len(existing)
    if new_count < 0:
        new_count = before - len(merged)
    return merged, max(new_count, 0)


def drop_comments_for_posts(df: pd.DataFrame, post_ids: set[str]) -> pd.DataFrame:
    if df.empty or not post_ids or "post_id" not in df.columns:
        return df
    return df[~df["post_id"].astype(str).isin(post_ids)].reset_index(drop=True)


def save_csv(path: Path, df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8")
