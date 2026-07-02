"""Fetcher alternativo: API web de Instagram (instatouch GraphQL suele estar roto)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from config import Settings

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
IG_APP_ID = "936619743392459"
HASHTAG_RE = re.compile(r"#[\w\u00C0-\u024F\u1E00-\u1EFF]+", re.UNICODE)


def _build_cookie(settings: Settings) -> str:
    return settings.session_cookie


def _request_json(
    url: str,
    settings: Settings,
    *,
    referer: str | None = None,
) -> dict[str, Any]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "X-IG-App-ID": IG_APP_ID,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": referer or settings.explore_referer,
        "cookie": _build_cookie(settings),
    }
    csrf = settings.csrf_token
    if csrf:
        headers["X-CSRFToken"] = csrf
        headers["x-csrftoken"] = csrf

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _request_html(
    url: str,
    settings: Settings,
    *,
    referer: str | None = None,
) -> str:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Referer": referer or settings.explore_referer,
        "cookie": _build_cookie(settings),
    }
    csrf = settings.csrf_token
    if csrf:
        headers["X-CSRFToken"] = csrf

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _find_hashtag_edges_in_obj(obj: Any) -> list[dict[str, Any]] | None:
    if isinstance(obj, dict):
        block = obj.get("edge_hashtag_to_media")
        if isinstance(block, dict):
            edges = block.get("edges") or []
            if edges:
                return edges
        for value in obj.values():
            found = _find_hashtag_edges_in_obj(value)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_hashtag_edges_in_obj(item)
            if found:
                return found
    return None


def _parse_hashtag_edges_from_html(html: str) -> list[dict[str, Any]]:
    for match in re.finditer(
        r'<script type="application/json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    ):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        edges = _find_hashtag_edges_in_obj(payload)
        if edges:
            return edges
    return []


def _extract_edges(user: dict[str, Any]) -> list[dict[str, Any]]:
    """Busca posts en distintas estructuras de respuesta IG."""
    candidates: list[list] = []

    for key in (
        "edge_owner_to_timeline_media",
        "edge_felix_video_timeline",
        "edge_media_collections",
    ):
        block = user.get(key) or {}
        if isinstance(block, dict) and block.get("edges"):
            candidates.append(block["edges"])

    for value in user.values():
        if isinstance(value, dict) and value.get("edges"):
            candidates.append(value["edges"])

    if not candidates:
        return []

    return max(candidates, key=len)


def _node_to_collector_item(
    node: dict[str, Any],
    username: str,
    *,
    source_search_hashtag: str = "",
) -> dict[str, Any]:
    caption_edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    description = caption_edges[0]["node"]["text"] if caption_edges else ""
    hashtags = HASHTAG_RE.findall(description)

    likes = node.get("edge_liked_by") or node.get("edge_media_preview_like") or {}
    comments = node.get("edge_media_to_comment") or {}

    return {
        "id": str(node.get("id", "")),
        "shortcode": node.get("shortcode", ""),
        "type": node.get("__typename", ""),
        "is_video": node.get("is_video", False),
        "description": description,
        "owner": {"id": str((node.get("owner") or {}).get("id", "")), "username": username},
        "comments": comments.get("count", 0) if isinstance(comments, dict) else 0,
        "likes": likes.get("count", 0) if isinstance(likes, dict) else 0,
        "views": node.get("video_view_count") or node.get("play_count") or 0,
        "taken_at_timestamp": node.get("taken_at_timestamp", ""),
        "url": f"https://www.instagram.com/p/{node.get('shortcode', '')}/",
        "hashtags": hashtags,
        "mentions": re.findall(r"@\w+", description),
        "source_search_hashtag": source_search_hashtag,
    }


def _item_from_rest_media(
    item: dict[str, Any],
    *,
    source_search_hashtag: str = "",
) -> dict[str, Any]:
    code = item.get("code") or item.get("shortcode") or ""
    caption_obj = item.get("caption") or {}
    description = caption_obj.get("text", "") if isinstance(caption_obj, dict) else ""
    user = item.get("user") or item.get("owner") or {}
    username = user.get("username", "")
    return {
        "id": str(item.get("pk") or item.get("id") or ""),
        "shortcode": code,
        "type": item.get("media_type", item.get("__typename", "")),
        "is_video": item.get("media_type") == 2 or item.get("is_video", False),
        "description": description,
        "owner": {
            "id": str(user.get("pk") or user.get("id") or ""),
            "username": username,
        },
        "comments": item.get("comment_count", 0),
        "likes": item.get("like_count", 0),
        "views": item.get("play_count") or item.get("view_count") or 0,
        "taken_at_timestamp": item.get("taken_at") or item.get("taken_at_timestamp", ""),
        "url": f"https://www.instagram.com/p/{code}/" if code else "",
        "hashtags": HASHTAG_RE.findall(description),
        "mentions": re.findall(r"@\w+", description),
        "source_search_hashtag": source_search_hashtag,
    }


def _items_from_graph_edges(
    edges: list[dict[str, Any]],
    *,
    source_search_hashtag: str = "",
) -> list[dict[str, Any]]:
    items = []
    for edge in edges:
        node = edge.get("node") if isinstance(edge, dict) else None
        if not node:
            continue
        username = (node.get("owner") or {}).get("username", "")
        items.append(
            _node_to_collector_item(
                node, username, source_search_hashtag=source_search_hashtag
            )
        )
    return items


def _tag_items(
    items: list[dict[str, Any]],
    tag: str,
) -> list[dict[str, Any]]:
    tag_norm = tag.lstrip("#").strip().lower()
    for item in items:
        item["source_search_hashtag"] = tag_norm
    return items


def _fetch_hashtag_from_explore_page(
    tag: str,
    count: int,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Página explore/tags con variant=nonpersonalized (menos sesgo algorítmico)."""
    explore_url = settings.hashtag_explore_url(tag)
    try:
        html = _request_html(
            explore_url,
            settings,
            referer=settings.explore_referer,
        )
    except Exception:  # noqa: BLE001
        return []

    edges = _parse_hashtag_edges_from_html(html)
    items = _items_from_graph_edges(edges, source_search_hashtag=tag)
    return items[:count]


def _sections_from_hashtag_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Recoge secciones de feed de hashtag (formato REST actual y legacy GraphQL)."""
    sections: list[dict[str, Any]] = []

    for feed_key in ("top", "recent"):
        feed = data.get(feed_key)
        if isinstance(feed, dict):
            sections.extend(feed.get("sections") or [])

    sections.extend(data.get("sections") or [])

    hashtag = data.get("hashtag")
    if isinstance(hashtag, dict):
        sections.extend(hashtag.get("sections") or [])

    return sections


def _items_from_web_info_data(
    data: dict[str, Any],
    tag: str,
) -> list[dict[str, Any]]:
    """Extrae posts del payload de tags/web_info (varios formatos de respuesta IG)."""
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    hashtag = data.get("hashtag")
    if isinstance(hashtag, dict):
        data = {**data, **hashtag}

    block = data.get("edge_hashtag_to_media")
    if isinstance(block, dict):
        items.extend(
            _items_from_graph_edges(
                block.get("edges") or [],
                source_search_hashtag=tag,
            )
        )
        seen_ids.update(str(i.get("id", "")) for i in items if i.get("id"))

    for section in _sections_from_hashtag_payload(data):
        layout = section.get("layout_content") or {}
        for media_wrap in layout.get("medias") or []:
            media = media_wrap.get("media") if isinstance(media_wrap, dict) else None
            media = media or media_wrap
            if not isinstance(media, dict):
                continue
            item = _item_from_rest_media(media, source_search_hashtag=tag)
            item_id = str(item.get("id", ""))
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            if item.get("shortcode") or item.get("id"):
                items.append(item)

    return items


def _fetch_hashtag_from_web_info_api(
    tag: str,
    settings: Settings,
    *,
    use_variant: bool | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Consulta tags/web_info y normaliza posts del feed top/recent."""
    params: dict[str, str] = {"tag_name": tag}
    include_variant = (
        settings.explore_variant if use_variant is None else use_variant
    )
    if include_variant:
        params["variant"] = include_variant

    urls = [
        "https://i.instagram.com/api/v1/tags/web_info/?"
        + urllib.parse.urlencode(params),
        "https://www.instagram.com/api/v1/tags/web_info/?"
        + urllib.parse.urlencode(params),
    ]

    last_err: str | None = None
    referer = settings.hashtag_explore_url(tag)

    for url in urls:
        try:
            payload = _request_json(url, settings, referer=referer)
        except urllib.error.HTTPError as exc:
            last_err = "auth_error" if exc.code in {401, 403} else f"http_{exc.code}"
            continue
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue

        data = payload.get("data") or payload
        if not isinstance(data, dict):
            last_err = "empty_hashtag"
            continue

        items = _items_from_web_info_data(data, tag)
        if items:
            return items, None

        media_count = data.get("media_count")
        if media_count in (0, "0"):
            last_err = "empty_hashtag"
        else:
            last_err = "empty_hashtag_feed"

    return [], last_err or "empty_hashtag"


def fetch_hashtag_posts(
    tag: str,
    count: int,
    settings: Settings,
) -> tuple[list[dict[str, Any]], str | None]:
    tag = tag.lstrip("#").strip()
    if not tag:
        return [], "empty_tag"

    last_err: str | None = None

    if settings.explore_variant:
        print(f"  Explore sin personalizar (variant={settings.explore_variant})")
        items = _fetch_hashtag_from_explore_page(tag, count, settings)
        if items:
            return _tag_items(items, tag), None

    items, err = _fetch_hashtag_from_web_info_api(tag, settings, use_variant=True)
    if items:
        print(f"  OK vía API web (web_info): {len(items)} posts")
        return items[:count], None
    last_err = err

    if settings.explore_variant:
        items, err = _fetch_hashtag_from_web_info_api(tag, settings, use_variant=False)
        if items:
            print(f"  OK vía API web (web_info, sin variant): {len(items)} posts")
            return items[:count], None
        last_err = err or last_err

        items = _fetch_hashtag_from_explore_page(tag, count, settings)
        if items:
            return _tag_items(items, tag), None
    else:
        items = _fetch_hashtag_from_explore_page(tag, count, settings)
        if items:
            return _tag_items(items, tag), None

    return [], last_err or "empty_hashtag"


def _fetch_user_feed_items(user_id: str, settings: Settings, count: int) -> list[dict[str, Any]]:
    url = f"https://i.instagram.com/api/v1/feed/user/{user_id}/"
    try:
        payload = _request_json(url, settings)
    except Exception:  # noqa: BLE001
        return []

    items_raw = payload.get("items") or []
    return [_item_from_rest_media(item) for item in items_raw[:count]]


def fetch_user_posts(
    username: str,
    count: int,
    settings: Settings,
) -> tuple[list[dict[str, Any]], str | None]:
    username = username.lstrip("@")
    url = (
        "https://i.instagram.com/api/v1/users/web_profile_info/?"
        + urllib.parse.urlencode({"username": username})
    )

    try:
        payload = _request_json(url, settings)
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return [], "auth_error"
        return [], f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)

    user = (payload.get("data") or {}).get("user") or payload.get("user")
    if not user:
        status = payload.get("status")
        if status == "fail":
            return [], "auth_error"
        return [], "no_user"

    edges = _extract_edges(user)
    items = [_node_to_collector_item(e["node"], username) for e in edges if e.get("node")]

    if not items:
        user_id = str(user.get("id") or user.get("pk") or "")
        if user_id:
            items = _fetch_user_feed_items(user_id, settings, count)

    if not items:
        return [], "empty_timeline"

    return items[:count], None


def save_collector_json(
    items: list[dict[str, Any]],
    settings: Settings,
    *,
    filename: str,
) -> tuple[Path, Path]:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    json_path = settings.raw_dir / f"{filename}.json"
    csv_path = settings.raw_dir / f"{filename}.csv"

    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    import csv

    if items:
        keys = [
            "id",
            "shortcode",
            "description",
            "owner.username",
            "likes",
            "comments",
            "views",
            "taken_at_timestamp",
            "url",
            "source_search_hashtag",
        ]
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=keys)
            writer.writeheader()
            for item in items:
                writer.writerow(
                    {
                        "id": item.get("id", ""),
                        "shortcode": item.get("shortcode", ""),
                        "description": item.get("description", ""),
                        "owner.username": (item.get("owner") or {}).get("username", ""),
                        "likes": item.get("likes", ""),
                        "comments": item.get("comments", ""),
                        "views": item.get("views", ""),
                        "taken_at_timestamp": item.get("taken_at_timestamp", ""),
                        "url": item.get("url", ""),
                        "source_search_hashtag": item.get("source_search_hashtag", ""),
                    }
                )

    return json_path, csv_path


def _extract_shortcode(post_ref: str) -> str:
    match = re.search(r"instagram\.com/(?:p|reel|tv)/([^/?#]+)", post_ref)
    if match:
        return match.group(1)
    return post_ref.strip().rstrip("/")


def _comment_from_rest(item: dict[str, Any]) -> dict[str, Any]:
    user = item.get("user") or {}
    return {
        "id": str(item.get("pk") or item.get("id") or ""),
        "text": item.get("text", "") or "",
        "created_at": item.get("created_at", ""),
        "owner": {
            "id": str(user.get("pk") or user.get("id") or ""),
            "username": user.get("username", "") or "",
        },
        "likes": item.get("comment_like_count", 0),
    }


def _resolve_media_id(
    media_ref: str,
    settings: Settings,
    *,
    referer: str,
    numeric_id: str | None = None,
) -> tuple[str | None, str | None]:
    media_ref = media_ref.strip().rstrip("/")
    if numeric_id and re.fullmatch(r"\d+", numeric_id):
        return numeric_id, None

    if re.fullmatch(r"\d+", media_ref):
        return media_ref, None

    shortcode = _extract_shortcode(media_ref)
    if not shortcode:
        return None, "invalid_media_ref"

    info_urls = [
        f"https://i.instagram.com/api/v1/media/{shortcode}/info/",
        f"https://www.instagram.com/api/v1/media/{shortcode}/info/",
    ]
    for url in info_urls:
        try:
            payload = _request_json(url, settings, referer=referer)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return None, "auth_error"
            continue
        except Exception:  # noqa: BLE001
            continue

        items = payload.get("items") or []
        if items:
            media_id = str(items[0].get("pk") or items[0].get("id") or "")
            if media_id:
                return media_id, None

    if numeric_id and re.fullmatch(r"\d+", numeric_id):
        return numeric_id, None

    return None, "media_not_found"


def fetch_post_comments(
    media_ref: str,
    count: int,
    settings: Settings,
    *,
    media_id: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    shortcode = _extract_shortcode(media_ref)
    referer = (
        f"https://www.instagram.com/p/{shortcode}/"
        if shortcode and "instagram.com" in media_ref
        else (f"https://www.instagram.com/p/{shortcode}/" if shortcode else settings.explore_referer)
    )

    media_id_resolved, err = _resolve_media_id(
        media_ref, settings, referer=referer, numeric_id=media_id
    )
    if not media_id_resolved:
        return [], err or "invalid_media_ref"

    collected: list[dict[str, Any]] = []
    max_id: str | None = None

    while len(collected) < count:
        params: dict[str, str] = {
            "can_support_threading": "true",
            "permalink_enabled": "false",
        }
        if max_id:
            params["max_id"] = max_id

        url = (
            f"https://i.instagram.com/api/v1/media/{media_id_resolved}/comments/?"
            + urllib.parse.urlencode(params)
        )
        try:
            payload = _request_json(url, settings, referer=referer)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return collected, "auth_error"
            if not collected:
                return [], f"http_{exc.code}"
            break
        except Exception as exc:  # noqa: BLE001
            if not collected:
                return [], str(exc)
            break

        batch = payload.get("comments") or []
        for item in batch:
            if not isinstance(item, dict):
                continue
            node = _comment_from_rest(item)
            if node.get("id"):
                collected.append(node)
            if len(collected) >= count:
                break

        max_id = payload.get("next_max_id")
        if not max_id or not batch:
            break

    if not collected:
        return [], "empty_comments"
    return collected[:count], None


def save_comments_json(
    items: list[dict[str, Any]],
    settings: Settings,
    *,
    filename: str,
) -> tuple[Path, Path]:
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    json_path = settings.raw_dir / f"{filename}.json"
    csv_path = settings.raw_dir / f"{filename}.csv"

    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    import csv

    keys = [
        "id",
        "text",
        "created_at",
        "owner.username",
        "likes",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "id": item.get("id", ""),
                    "text": item.get("text", ""),
                    "created_at": item.get("created_at", ""),
                    "owner.username": (item.get("owner") or {}).get("username", ""),
                    "likes": item.get("likes", ""),
                }
            )

    return json_path, csv_path
