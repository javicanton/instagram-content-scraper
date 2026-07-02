"""Análisis de polarización / sentimiento en comentarios (positivo, negativo, neutral)."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

from language_detect import is_emoji_only_text

LEXICON_PATH = Path(__file__).resolve().parent / "sentiment_lexicon.json"
URL_RE = re.compile(r"https?://\S+|www\.\S+")
MULTISPACE_RE = re.compile(r"\s+")

NEUTRAL_THRESHOLD = 0.15


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    value = str(text).strip().lower()
    value = unicodedata.normalize("NFKC", value)
    value = URL_RE.sub(" ", value)
    value = MULTISPACE_RE.sub(" ", value).strip()
    return value


def _phrase_matches(text: str, phrase: str) -> bool:
    if not phrase or not text:
        return False
    if " " in phrase:
        return phrase in text
    return bool(re.search(rf"\b{re.escape(phrase)}\b", text, flags=re.IGNORECASE))


def _resolve_language(language: str) -> str:
    code = (language or "").lower().split("-")[0]
    if code in {"es", "pt", "en"}:
        return code
    return "es"


@lru_cache(maxsize=1)
def _load_lexicon() -> dict:
    if not LEXICON_PATH.exists():
        return {
            "negators": [],
            "intensifiers": [],
            "positive": {"es": [], "pt": [], "en": []},
            "negative": {"es": [], "pt": [], "en": []},
            "emoji_positive": [],
            "emoji_negative": [],
        }
    return json.loads(LEXICON_PATH.read_text(encoding="utf-8"))


def _negated_near(text: str, phrase: str, window: int = 4) -> bool:
    """True si hay un negador en las N palabras previas a la coincidencia."""
    if " " in phrase:
        idx = text.find(phrase)
        if idx < 0:
            return False
        prefix = text[:idx].split()[-window:]
    else:
        match = re.search(rf"\b{re.escape(phrase)}\b", text, flags=re.IGNORECASE)
        if not match:
            return False
        prefix = text[: match.start()].split()[-window:]

    lexicon = _load_lexicon()
    negators = {_normalize_text(n) for n in lexicon.get("negators", [])}
    return any(token in negators for token in prefix)


def _intensifier_near(text: str, phrase: str, window: int = 2) -> bool:
    if " " in phrase:
        idx = text.find(phrase)
        if idx < 0:
            return False
        prefix = text[:idx].split()[-window:]
    else:
        match = re.search(rf"\b{re.escape(phrase)}\b", text, flags=re.IGNORECASE)
        if not match:
            return False
        prefix = text[: match.start()].split()[-window:]

    lexicon = _load_lexicon()
    intensifiers = {_normalize_text(i) for i in lexicon.get("intensifiers", [])}
    return any(token in intensifiers for token in prefix)


def _score_lexicon(text: str, language: str) -> tuple[float, float, list[str]]:
    lexicon = _load_lexicon()
    lang = _resolve_language(language)
    pos_score = 0.0
    neg_score = 0.0
    signals: list[str] = []

    for polarity, bucket in (("pos", "positive"), ("neg", "negative")):
        terms = lexicon.get(bucket, {}).get(lang, [])
        fallback = lexicon.get(bucket, {}).get("es", [])
        for phrase in list(terms) + [t for t in fallback if t not in terms]:
            if not _phrase_matches(text, phrase):
                continue
            weight = 1.0
            if _intensifier_near(text, phrase):
                weight *= 1.5
            if _negated_near(text, phrase):
                weight *= -1.0
            if polarity == "pos":
                if weight < 0:
                    neg_score += abs(weight)
                    signals.append(f"-negated_pos:{phrase}")
                else:
                    pos_score += weight
                    signals.append(f"+pos:{phrase}")
            else:
                if weight < 0:
                    pos_score += abs(weight)
                    signals.append(f"-negated_neg:{phrase}")
                else:
                    neg_score += weight
                    signals.append(f"+neg:{phrase}")

    return pos_score, neg_score, signals


def _score_emojis(raw: str) -> tuple[float, float, list[str]]:
    lexicon = _load_lexicon()
    pos = 0.0
    neg = 0.0
    signals: list[str] = []

    for emoji in lexicon.get("emoji_positive", []):
        count = raw.count(emoji)
        if count:
            pos += count * 0.8
            signals.append(f"+emoji_pos:{emoji}x{count}")

    for emoji in lexicon.get("emoji_negative", []):
        count = raw.count(emoji)
        if count:
            neg += count * 0.8
            signals.append(f"+emoji_neg:{emoji}x{count}")

    return pos, neg, signals


def _score_punctuation(raw: str) -> tuple[float, float, list[str]]:
    """Señales ligeras: mayúsculas sostenidas y repetición de signos."""
    pos = 0.0
    neg = 0.0
    signals: list[str] = []

    if re.search(r"!{2,}", raw):
        neg += 0.3
        signals.append("+punct:!!")
    if re.search(r"\?{2,}", raw):
        neg += 0.2
        signals.append("+punct:??")

    letters = re.sub(r"[^a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]", "", raw)
    if len(letters) >= 8:
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio > 0.6:
            neg += 0.4
            signals.append("+punct:caps")

    return pos, neg, signals


def analyze_sentiment(text: str, *, language: str = "") -> dict[str, str | float]:
    """
    Devuelve polaridad del texto: positive | negative | neutral.

    sentiment_polarity ∈ [-1, 1] (negativo ← 0 → positivo).
    """
    raw = str(text or "")
    cleaned = _normalize_text(raw)

    if not cleaned and not raw.strip():
        return {
            "sentiment_label": "neutral",
            "sentiment_polarity": 0.0,
            "sentiment_positive_score": 0.0,
            "sentiment_negative_score": 0.0,
            "sentiment_signals": "",
        }

    if is_emoji_only_text(raw):
        pos, neg, signals = _score_emojis(raw)
    else:
        pos_lex, neg_lex, lex_signals = _score_lexicon(cleaned, language)
        pos_emo, neg_emo, emoji_signals = _score_emojis(raw)
        pos_punct, neg_punct, punct_signals = _score_punctuation(raw)
        pos = pos_lex + pos_emo + pos_punct
        neg = neg_lex + neg_emo + neg_punct
        signals = lex_signals + emoji_signals + punct_signals

    total = pos + neg
    if total == 0:
        label = "neutral"
        polarity = 0.0
    else:
        polarity = (pos - neg) / total
        if polarity > NEUTRAL_THRESHOLD:
            label = "positive"
        elif polarity < -NEUTRAL_THRESHOLD:
            label = "negative"
        else:
            label = "neutral"

    return {
        "sentiment_label": label,
        "sentiment_polarity": round(polarity, 3),
        "sentiment_positive_score": round(pos, 3),
        "sentiment_negative_score": round(neg, 3),
        "sentiment_signals": ";".join(signals[:25]),
    }


def summarize_sentiment(
    df: pd.DataFrame,
    *,
    group_col: str | None = None,
) -> pd.DataFrame:
    """Agrega recuentos y polarización por grupo (o corpus completo)."""
    if df.empty or "sentiment_label" not in df.columns:
        return pd.DataFrame(
            columns=[
                "group",
                "n_comments",
                "positive",
                "negative",
                "neutral",
                "positive_pct",
                "negative_pct",
                "neutral_pct",
                "mean_polarity",
                "polarization_index",
            ]
        )

    work = df.copy()
    if group_col and group_col in work.columns:
        groups = work.groupby(group_col, dropna=False)
    else:
        work["_group"] = "all"
        groups = work.groupby("_group")

    rows: list[dict] = []
    for group_name, subset in groups:
        n = len(subset)
        counts = subset["sentiment_label"].value_counts()
        pos = int(counts.get("positive", 0))
        neg = int(counts.get("negative", 0))
        neu = int(counts.get("neutral", 0))
        polarities = pd.to_numeric(subset.get("sentiment_polarity", 0), errors="coerce").fillna(0)

        rows.append(
            {
                "group": str(group_name),
                "n_comments": n,
                "positive": pos,
                "negative": neg,
                "neutral": neu,
                "positive_pct": round(100 * pos / n, 1) if n else 0.0,
                "negative_pct": round(100 * neg / n, 1) if n else 0.0,
                "neutral_pct": round(100 * neu / n, 1) if n else 0.0,
                "mean_polarity": round(float(polarities.mean()), 3) if n else 0.0,
                "polarization_index": round((pos + neg) / n, 3) if n else 0.0,
            }
        )

    return pd.DataFrame(rows).sort_values("group")


def add_sentiment_columns(df: pd.DataFrame, *, text_col: str = "comment_text") -> pd.DataFrame:
    """Añade columnas de sentimiento a un DataFrame de comentarios."""
    if df.empty:
        return df

    out = df.copy()
    labels: list[str] = []
    polarities: list[str] = []
    pos_scores: list[str] = []
    neg_scores: list[str] = []
    signals: list[str] = []

    for _, row in out.iterrows():
        text = str(row.get(text_col, "") or "")
        language = str(row.get("language", "") or "")
        result = analyze_sentiment(text, language=language)
        labels.append(str(result["sentiment_label"]))
        polarities.append(str(result["sentiment_polarity"]))
        pos_scores.append(str(result["sentiment_positive_score"]))
        neg_scores.append(str(result["sentiment_negative_score"]))
        signals.append(str(result["sentiment_signals"]))

    out["sentiment_label"] = labels
    out["sentiment_polarity"] = polarities
    out["sentiment_positive_score"] = pos_scores
    out["sentiment_negative_score"] = neg_scores
    out["sentiment_signals"] = signals
    return out


def write_sentiment_summaries(df: pd.DataFrame, paths) -> None:
    """Escribe sentiment_summary_<corpus>.csv y sentiment_by_language_<corpus>.csv."""
    if df.empty or "sentiment_label" not in df.columns:
        return

    paths.output_dir.mkdir(parents=True, exist_ok=True)
    overall = summarize_sentiment(df)
    overall_path = paths.sentiment_summary
    overall.to_csv(overall_path, index=False, encoding="utf-8")
    print(f"  Polarización (corpus): {dict(zip(overall['group'], overall['polarization_index']))}")

    if "language" in df.columns:
        by_lang = summarize_sentiment(df, group_col="language")
        by_lang_path = paths.sentiment_by_language
        by_lang.to_csv(by_lang_path, index=False, encoding="utf-8")


def append_sentiment_to_cluster_summary(
    summary_df: pd.DataFrame,
    enriched_df: pd.DataFrame,
) -> pd.DataFrame:
    """Añade columnas de polarización media por cluster a clusters_summary."""
    if summary_df.empty or enriched_df.empty:
        return summary_df

    if "cluster_id" not in enriched_df.columns or "sentiment_label" not in enriched_df.columns:
        return summary_df

    by_cluster = summarize_sentiment(enriched_df, group_col="cluster_id")
    lookup = {str(row["group"]): row for _, row in by_cluster.iterrows()}

    out = summary_df.copy()
    for col in (
        "sentiment_positive_pct",
        "sentiment_negative_pct",
        "sentiment_neutral_pct",
        "mean_polarity",
        "polarization_index",
    ):
        if col not in out.columns:
            out[col] = ""

    for idx, row in out.iterrows():
        cid = str(row.get("cluster_id", ""))
        stats = lookup.get(cid)
        if stats is None:
            continue
        out.at[idx, "sentiment_positive_pct"] = str(stats["positive_pct"])
        out.at[idx, "sentiment_negative_pct"] = str(stats["negative_pct"])
        out.at[idx, "sentiment_neutral_pct"] = str(stats["neutral_pct"])
        out.at[idx, "mean_polarity"] = str(stats["mean_polarity"])
        out.at[idx, "polarization_index"] = str(stats["polarization_index"])

    return out
