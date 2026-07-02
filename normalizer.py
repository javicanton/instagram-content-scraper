"""Normalización de salidas crudas de instatouch al esquema unificado."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

POST_COLUMNS = [
    "platform",
    "post_id",
    "post_url",
    "profile_username",
    "caption",
    "hashtags",
    "mentions",
    "media_type",
    "published_at",
    "like_count",
    "comment_count",
    "view_count",
    "source_mode",
    "source_hashtag",
    "corpus_id",
    "scraped_at",
]

HASHTAG_RE = re.compile(r"#[\w\u00C0-\u024F\u1E00-\u1EFF]+", re.UNICODE)

COMMENT_COLUMNS = [
    "platform",
    "post_id",
    "comment_id",
    "parent_comment_id",
    "author_username",
    "comment_text",
    "like_count",
    "published_at",
    "corpus_id",
    "scraped_at",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _to_str(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _timestamp_to_iso(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = _to_str(value)
    if not text:
        return ""
    if re.match(r"^\d{10,13}$", text):
        ts = int(text)
        if ts > 10_000_000_000:
            ts //= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).replace(microsecond=0).isoformat()
    return text


def _join_list_field(value: Any, prefix: str = "") -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, list):
        items = [_to_str(v) for v in value if _to_str(v)]
        return ";".join(items)
    text = _to_str(value)
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, list):
                return ";".join(_to_str(v) for v in parsed if _to_str(v))
        except (json.JSONDecodeError, ValueError):
            pass
    if prefix and text and not text.startswith(prefix):
        parts = re.findall(rf"{re.escape(prefix)}\w+", text)
        return ";".join(parts)
    return text.replace(",", ";")


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row[key] is not None and not (
            isinstance(row[key], float) and pd.isna(row[key])
        ):
            val = row[key]
            if _to_str(val):
                return val
    return None


def _load_raw(path: Path) -> pd.DataFrame:
    if not path or not path.exists():
        return pd.DataFrame()

    if path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, list):
            return pd.json_normalize(data)
        if isinstance(data, dict) and "collector" in data:
            return pd.json_normalize(data["collector"])
        return pd.json_normalize([data])

    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def _prefer_json(csv_path: Path | None, json_path: Path | None) -> pd.DataFrame:
    if json_path and json_path.exists():
        df = _load_raw(json_path)
        if not df.empty:
            return df
    if csv_path and csv_path.exists():
        return _load_raw(csv_path)
    return pd.DataFrame()


def extract_shortcode(post_ref: str) -> str:
    match = re.search(r"instagram\.com/(?:p|reel|tv)/([^/?#]+)", post_ref)
    if match:
        return match.group(1)
    return post_ref.strip().rstrip("/")


def build_post_url(shortcode: str | None, url: str | None = None) -> str:
    if url and "instagram.com" in url:
        sc = extract_shortcode(url)
        if sc:
            return f"https://www.instagram.com/p/{sc}/"
        return url.split("?")[0].rstrip("/") + "/"
    if shortcode:
        return f"https://www.instagram.com/p/{shortcode}/"
    return ""


def resolve_post_ref(row: dict[str, Any] | pd.Series) -> str:
    """Referencia válida para scrape de comentarios (permalink IG o media_id numérico)."""
    if isinstance(row, pd.Series):
        row = row.to_dict()

    url = _to_str(row.get("post_url"))
    if "instagram.com" in url:
        sc = extract_shortcode(url)
        if sc:
            return build_post_url(sc)
        return url.split("?")[0].rstrip("/") + "/"

    sc = _to_str(_first_present(row, "shortcode")) or extract_shortcode(url)
    if sc:
        return build_post_url(sc)

    post_id = _to_str(row.get("post_id"))
    if post_id and re.match(r"^\d+$", post_id):
        return post_id

    return post_id or url


def normalize_posts(
    csv_path: Path | None,
    *,
    json_path: Path | None = None,
    source_mode: str,
    default_username: str = "",
    default_source_hashtag: str = "",
) -> pd.DataFrame:
    raw = _prefer_json(csv_path, json_path)
    if raw.empty:
        return pd.DataFrame(columns=POST_COLUMNS)

    scraped_at = _now_iso()
    rows: list[dict[str, str]] = []

    for _, series in raw.iterrows():
        row = series.to_dict()
        post_id = _to_str(
            _first_present(row, "id", "post_id", "shortcode")
        )
        shortcode = _to_str(_first_present(row, "shortcode"))
        if not post_id and shortcode:
            post_id = shortcode

        caption = _to_str(
            _first_present(row, "description", "caption", "edge_media_to_caption")
        )
        hashtags = _join_list_field(
            _first_present(row, "hashtags", "hashtag"),
            "#",
        )
        if not hashtags and caption:
            hashtags = ";".join(HASHTAG_RE.findall(caption))

        mentions = _join_list_field(
            _first_present(row, "mentions", "mention"),
            "@",
        )
        if not mentions and caption:
            mentions = ";".join(re.findall(r"@\w+", caption))

        media_type = _to_str(
            _first_present(row, "type", "media_type", "isVideo", "is_video")
        )
        if media_type.lower() in ("true", "1"):
            media_type = "video"
        elif media_type.lower() in ("false", "0"):
            media_type = "image"

        published = _timestamp_to_iso(
            _first_present(row, "takenAtTimestamp", "taken_at_timestamp", "takenAtGMT")
        )

        profile = _to_str(
            _first_present(
                row,
                "ownerUsername",
                "owner.username",
                "owner_username",
                "username",
            )
        ) or default_username

        source_hashtag = _to_str(
            _first_present(row, "source_search_hashtag", "source_hashtag")
        ) or default_source_hashtag
        source_hashtag = source_hashtag.lstrip("#").lower()

        rows.append(
            {
                "platform": "instagram",
                "post_id": post_id,
                "post_url": build_post_url(
                    shortcode,
                    _to_str(_first_present(row, "url"))
                    if "instagram.com" in _to_str(_first_present(row, "url"))
                    else None,
                ),
                "profile_username": profile.lstrip("@"),
                "caption": caption,
                "hashtags": hashtags,
                "mentions": mentions,
                "media_type": media_type,
                "published_at": published,
                "like_count": _to_str(_first_present(row, "likes", "like_count")),
                "comment_count": _to_str(
                    _first_present(row, "comments", "comment_count")
                ),
                "view_count": _to_str(_first_present(row, "views", "view_count")),
                "source_mode": source_mode,
                "source_hashtag": source_hashtag,
                "corpus_id": _to_str(_first_present(row, "corpus_id")),
                "scraped_at": scraped_at,
            }
        )

    return pd.DataFrame(rows, columns=POST_COLUMNS)


def normalize_comments(
    csv_path: Path | None,
    *,
    json_path: Path | None = None,
    post_id: str,
) -> pd.DataFrame:
    raw = _prefer_json(csv_path, json_path)
    if raw.empty:
        return pd.DataFrame(columns=COMMENT_COLUMNS)

    scraped_at = _now_iso()
    rows: list[dict[str, str]] = []

    for _, series in raw.iterrows():
        row = series.to_dict()
        comment_id = _to_str(_first_present(row, "id", "comment_id"))
        if not comment_id:
            continue

        rows.append(
            {
                "platform": "instagram",
                "post_id": _to_str(post_id),
                "comment_id": comment_id,
                "parent_comment_id": _to_str(
                    _first_present(row, "parent_comment_id", "parent_id")
                ),
                "author_username": _to_str(
                    _first_present(
                        row,
                        "owner_username",
                        "owner.username",
                        "ownerUsername",
                        "user.username",
                        "username",
                    )
                ).lstrip("@"),
                "comment_text": _to_str(
                    _first_present(row, "text", "comment_text", "comment")
                ),
                "like_count": _to_str(
                    _first_present(row, "likes", "like_count", "comment_like_count")
                ),
                "published_at": _timestamp_to_iso(
                    _first_present(row, "created_at", "createdAt", "timestamp")
                ),
                "corpus_id": _to_str(_first_present(row, "corpus_id")),
                "scraped_at": scraped_at,
            }
        )

    return pd.DataFrame(rows, columns=COMMENT_COLUMNS)


def make_post_stub(post_ref: str, source_mode: str = "post") -> pd.DataFrame:
    shortcode = extract_shortcode(post_ref)
    scraped_at = _now_iso()
    return pd.DataFrame(
        [
            {
                "platform": "instagram",
                "post_id": shortcode,
                "post_url": build_post_url(shortcode),
                "profile_username": "",
                "caption": "",
                "hashtags": "",
                "mentions": "",
                "media_type": "",
                "published_at": "",
                "like_count": "",
                "comment_count": "",
                "view_count": "",
                "source_mode": source_mode,
                "source_hashtag": "",
                "corpus_id": "",
                "scraped_at": scraped_at,
            }
        ],
        columns=POST_COLUMNS,
    )
