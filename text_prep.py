"""Preprocesado de texto para análisis de narrativas."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from language_detect import (
    detect_language,
    detect_language_detailed,
    is_emoji_only_text,
    language_allowed,
)
from nlp_stopwords import get_stopwords
from sentiment import analyze_sentiment

URL_RE = re.compile(r"https?://\S+|www\.\S+")
MULTISPACE_RE = re.compile(r"\s+")
REPEAT_CHAR_RE = re.compile(r"(.)\1{3,}")
HASHTAG_RE = re.compile(r"#[\w\u00C0-\u024F\u1E00-\u1EFF]+", re.UNICODE)
MENTION_RE = re.compile(r"@([A-Za-z0-9._]{2,30})")
PUNCT_RE = re.compile(r"[^\w\sáéíóúüñãõç]", re.UNICODE)
TOKEN_RE = re.compile(r"[\wáéíóúüñãõç]{3,}", re.UNICODE | re.IGNORECASE)
SPAM_RE = re.compile(
    r"(send me this post|please send me|this shot is really|great please|"
    r"check out my profile|follow for follow|dm me|link in bio)",
    re.IGNORECASE,
)
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002700-\U000027BF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "]+",
    flags=re.UNICODE,
)


def normalize_text(text: str) -> str:
    if not text or pd.isna(text):
        return ""
    value = str(text).strip().lower()
    value = unicodedata.normalize("NFKC", value)
    value = URL_RE.sub(" ", value)
    value = MENTION_RE.sub(" ", value)
    value = HASHTAG_RE.sub(" ", value)
    value = EMOJI_PATTERN.sub(" ", value)
    value = REPEAT_CHAR_RE.sub(r"\1\1", value)
    value = MULTISPACE_RE.sub(" ", value).strip()
    return value


def prepare_text_for_clustering(text: str, *, language: str = "") -> str:
    """Tokeniza y elimina stopwords para TF-IDF / clustering."""
    cleaned = normalize_text(text)
    if not cleaned:
        return ""

    stopwords = get_stopwords(language)
    cleaned = PUNCT_RE.sub(" ", cleaned)
    tokens: list[str] = []
    for match in TOKEN_RE.finditer(cleaned):
        tok = match.group(0).lower()
        if tok in stopwords:
            continue
        if tok.isdigit():
            continue
        tokens.append(tok)

    return " ".join(tokens)


def is_spam_comment(text: str) -> bool:
    if not text or pd.isna(text):
        return False
    return bool(SPAM_RE.search(str(text)))


def count_cluster_tokens(text: str, *, language: str = "") -> int:
    prepared = prepare_text_for_clustering(text, language=language)
    if not prepared:
        return 0
    return len(prepared.split())


def extract_hashtags(text: str) -> str:
    if not text:
        return ""
    tags = HASHTAG_RE.findall(str(text))
    return ";".join(sorted(set(tags)))


def extract_mentions(text: str) -> str:
    if not text:
        return ""
    mentions = re.findall(r"@([A-Za-z0-9._]{2,30})", str(text))
    return ";".join(sorted({m.lower() for m in mentions}))


def is_emoji_only(text: str) -> bool:
    """True si el comentario no contiene letras sustantivas (solo emojis/símbolos)."""
    return is_emoji_only_text(text)


def is_usable_comment(text: str, *, min_length: int = 15) -> bool:
    if is_emoji_only(text):
        return False
    if is_spam_comment(text):
        return False
    cleaned = normalize_text(text)
    if len(cleaned) < min_length:
        return False
    if count_cluster_tokens(text) < 3:
        return False
    return True


def enrich_comments(
    comments_df: pd.DataFrame,
    posts_df: pd.DataFrame,
    *,
    min_length: int = 15,
    languages: list[str] | None = None,
    min_language_confidence: float = 0.72,
    min_language_margin: float = 0.12,
    keep_unknown_language: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if comments_df.empty:
        return pd.DataFrame(), pd.DataFrame()

    posts_lookup = {}
    if not posts_df.empty:
        for _, row in posts_df.iterrows():
            posts_lookup[str(row.get("post_id", ""))] = row

    rows: list[dict] = []
    excluded: list[dict] = []
    for _, row in comments_df.iterrows():
        text = str(row.get("comment_text", "") or "")
        cleaned = normalize_text(text)
        if not is_usable_comment(text, min_length=min_length):
            continue

        language, confidence = detect_language(text)
        _, _, scores = detect_language_detailed(text)
        if not language_allowed(
            language,
            confidence,
            scores,
            allowed=languages,
            min_confidence=min_language_confidence,
            min_margin=min_language_margin,
            keep_unknown=keep_unknown_language,
        ):
            excluded.append(
                {
                    "comment_id": str(row.get("comment_id", "")),
                    "post_id": str(row.get("post_id", "")),
                    "language": language,
                    "language_confidence": str(confidence),
                    "comment_text": text[:300],
                    "exclusion_reason": "language_filter",
                }
            )
            continue

        post_id = str(row.get("post_id", ""))
        post_row = posts_lookup.get(post_id, {})
        profile_username = ""
        if isinstance(post_row, pd.Series):
            profile_username = str(post_row.get("profile_username", "") or "")

        cluster_text = prepare_text_for_clustering(text, language=language)
        sentiment = analyze_sentiment(text, language=language)

        rows.append(
            {
                "comment_id": str(row.get("comment_id", "")),
                "post_id": post_id,
                "profile_username": profile_username.lstrip("@"),
                "author_username": str(row.get("author_username", "") or "").lstrip("@"),
                "comment_text": text,
                "comment_text_clean": cleaned,
                "comment_text_cluster": cluster_text,
                "language": language,
                "language_confidence": str(confidence),
                "comment_length": len(cleaned),
                "cluster_token_count": len(cluster_text.split()) if cluster_text else 0,
                "hashtags": extract_hashtags(text),
                "mentions": extract_mentions(text),
                "like_count": str(row.get("like_count", "") or ""),
                "published_at": str(row.get("published_at", "") or ""),
                "discourse_label": "unlabeled",
                "discourse_stance": "unlabeled",
                "discourse_category_id": "",
                "discourse_category_label": "",
                "discourse_source": "pending",
                "discourse_score_feminist": "",
                "discourse_score_antifeminist": "",
                "discourse_signals": "",
                "sentiment_label": sentiment["sentiment_label"],
                "sentiment_polarity": str(sentiment["sentiment_polarity"]),
                "sentiment_positive_score": str(sentiment["sentiment_positive_score"]),
                "sentiment_negative_score": str(sentiment["sentiment_negative_score"]),
                "sentiment_signals": sentiment["sentiment_signals"],
            }
        )

    return pd.DataFrame(rows), pd.DataFrame(excluded)
