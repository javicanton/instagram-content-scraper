"""Recuperación de posts desde data/raw e inspección de progreso por hashtag."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from normalizer import POST_COLUMNS, build_post_url, extract_shortcode, normalize_posts


def _tag_key(tag: str) -> str:
    return tag.lstrip("#").strip().lower()


def parse_comment_count(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    try:
        return max(int(float(text)), 0)
    except ValueError:
        return 0


def posts_with_comment_activity(posts_df: pd.DataFrame) -> pd.DataFrame:
    """Posts donde Instagram reporta al menos un comentario (comment_count > 0)."""
    if posts_df.empty or "comment_count" not in posts_df.columns:
        return posts_df
    counts = posts_df["comment_count"].map(parse_comment_count)
    return posts_df[counts > 0].copy()


def find_latest_hashtag_raw(raw_dir: Path, tag: str) -> tuple[Path | None, Path | None]:
    """Devuelve el json/csv raw más reciente para un hashtag."""
    key = _tag_key(tag)
    if not raw_dir.exists():
        return None, None

    candidates: list[Path] = []
    for path in raw_dir.glob("hashtag_*.json"):
        stem = path.stem  # hashtag_tag_timestamp
        match = re.match(r"hashtag_(.+)_\d+$", stem, re.IGNORECASE)
        if match and _tag_key(match.group(1)) == key:
            candidates.append(path)

    if not candidates:
        return None, None

    json_path = max(candidates, key=lambda p: p.stat().st_mtime)
    csv_path = json_path.with_suffix(".csv")
    return json_path, csv_path if csv_path.exists() else None


def import_hashtag_posts_from_raw(
    tag: str,
    raw_dir: Path,
    *,
    corpus_id: str = "",
    max_posts: int | None = None,
) -> pd.DataFrame:
    """Normaliza posts de un hashtag desde el raw guardado por instatouch/API."""
    json_path, csv_path = find_latest_hashtag_raw(raw_dir, tag)
    if not json_path and not csv_path:
        return pd.DataFrame(columns=POST_COLUMNS)

    posts_df = normalize_posts(
        csv_path,
        json_path=json_path,
        source_mode="hashtags",
        default_source_hashtag=_tag_key(tag),
    )
    if posts_df.empty:
        return posts_df

    posts_df = posts_df.copy()
    posts_df["source_mode"] = "hashtags"
    if corpus_id:
        posts_df["corpus_id"] = corpus_id
    if max_posts and max_posts > 0:
        posts_df = posts_df.head(max_posts)
    return posts_df


def import_all_hashtags_from_raw(
    tags: list[str],
    raw_dir: Path,
    *,
    corpus_id: str = "",
    max_posts_per_tag: int | None = None,
) -> pd.DataFrame:
    """Importa posts de varios hashtags desde raw (el archivo más reciente por tag)."""
    parts: list[pd.DataFrame] = []
    for tag in tags:
        df = import_hashtag_posts_from_raw(
            tag,
            raw_dir,
            corpus_id=corpus_id,
            max_posts=max_posts_per_tag,
        )
        if not df.empty:
            parts.append(df)
    if not parts:
        return pd.DataFrame(columns=POST_COLUMNS)
    return pd.concat(parts, ignore_index=True)


def load_existing_output(output_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lee posts.csv y comments.csv si existen."""
    posts_path = output_dir / "posts.csv"
    comments_path = output_dir / "comments.csv"

    posts_df = (
        pd.read_csv(posts_path, dtype=str, keep_default_na=False, encoding="utf-8")
        if posts_path.exists()
        else pd.DataFrame(columns=POST_COLUMNS)
    )
    comments_df = (
        pd.read_csv(comments_path, dtype=str, keep_default_na=False, encoding="utf-8")
        if comments_path.exists()
        else pd.DataFrame()
    )
    return posts_df, comments_df


def hashtag_status(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    tag: str,
    *,
    with_comments: bool,
) -> str:
    """
    Estado de un hashtag: pending | needs_comments | complete.

    complete = hay posts y (sin comentarios pedidos o todos los posts tienen comentarios).
    """
    key = _tag_key(tag)
    if posts_df.empty or "source_hashtag" not in posts_df.columns:
        return "pending"

    tag_posts = posts_df[posts_df["source_hashtag"].astype(str).str.lower() == key]
    if tag_posts.empty:
        return "pending"

    if not with_comments:
        return "complete"

    actionable = posts_with_comment_activity(tag_posts)
    if actionable.empty:
        return "complete"

    post_ids = set(actionable["post_id"].astype(str))
    if comments_df.empty or "post_id" not in comments_df.columns:
        return "needs_comments"

    tag_comments = comments_df[comments_df["post_id"].astype(str).isin(post_ids)]
    if comments_look_empty(tag_comments) and not tag_comments.empty:
        return "needs_comments"

    if "comment_text" in comments_df.columns:
        text_by_post = (
            tag_comments.groupby("post_id")["comment_text"]
            .apply(lambda s: s.fillna("").astype(str).str.strip().ne("").any())
        )
        commented = set(text_by_post[text_by_post].index.astype(str))
    else:
        commented = set(tag_comments["post_id"].astype(str))

    if len(commented) >= len(post_ids):
        return "complete"
    return "needs_comments"


def posts_needing_comments(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    tag: str,
) -> pd.DataFrame:
    """Posts de un hashtag que aún no tienen ningún comentario en comments.csv."""
    key = _tag_key(tag)
    tag_posts = posts_df[posts_df["source_hashtag"].astype(str).str.lower() == key].copy()
    if tag_posts.empty:
        return tag_posts

    tag_posts = posts_with_comment_activity(tag_posts)
    if tag_posts.empty:
        return tag_posts.reset_index(drop=True)

    if comments_df.empty or "post_id" not in comments_df.columns:
        return tag_posts.reset_index(drop=True)

    if "comment_text" in comments_df.columns:
        text_by_post = (
            comments_df.groupby("post_id")["comment_text"]
            .apply(lambda s: s.fillna("").astype(str).str.strip().ne("").any())
        )
        commented = set(text_by_post[text_by_post].index.astype(str))
    else:
        commented = set(comments_df["post_id"].astype(str))

    mask = ~tag_posts["post_id"].astype(str).isin(commented)
    return tag_posts[mask].reset_index(drop=True)


def build_media_id_shortcode_map(raw_dir: Path) -> dict[str, str]:
    """Mapa post_id numérico → shortcode desde JSON raw de hashtags."""
    mapping: dict[str, str] = {}
    if not raw_dir.exists():
        return mapping

    for path in raw_dir.glob("hashtag_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            media_id = str(item.get("id") or "").strip()
            shortcode = str(item.get("shortcode") or "").strip()
            if media_id and shortcode:
                mapping[media_id] = shortcode
    return mapping


def repair_post_urls(posts_df: pd.DataFrame, raw_dir: Path) -> pd.DataFrame:
    """Reconstruye permalinks instagram.com/p/... desde shortcodes en data/raw."""
    if posts_df.empty:
        return posts_df

    mapping = build_media_id_shortcode_map(raw_dir)
    df = posts_df.copy()
    fixed_urls: list[str] = []

    for _, row in df.iterrows():
        url = str(row.get("post_url") or "")
        if "instagram.com/p/" in url or "instagram.com/reel/" in url:
            fixed_urls.append(url.split("?")[0].rstrip("/") + "/")
            continue

        post_id = str(row.get("post_id") or "")
        shortcode = mapping.get(post_id) or extract_shortcode(url)
        fixed_urls.append(build_post_url(shortcode) if shortcode else url)

    df["post_url"] = fixed_urls
    return df


def comments_look_empty(comments_df: pd.DataFrame) -> bool:
    """True si hay filas pero casi ninguna tiene texto de comentario."""
    if comments_df.empty or "comment_text" not in comments_df.columns:
        return False
    texts = comments_df["comment_text"].fillna("").astype(str).str.strip()
    with_text = int((texts != "").sum())
    return with_text == 0 and len(comments_df) > 0
