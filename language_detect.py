"""Detección de idioma para filtrar comentarios antes del análisis."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd
from langdetect import DetectorFactory, LangDetectException, detect_langs

# Resultados reproducibles entre ejecuciones.
DetectorFactory.seed = 0

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

# Portugués: palabras que langdetect suele confundir con español.
_PT_STRONG = re.compile(
    r"\b("
    r"nao|não|você|voce|vocês|voces|pra|pro|tambem|também|entao|então|"
    r"mesmo|mesma|gente|mulher|mulheres|homem|homens|isso|essa|esse|estao|estão|"
    r"estamos|fazer|faz|pq|qnd|tb|tbm|né|ne|pra|la|lá|aqui|ai|aí|"
    r"ninguem|ninguém|beleza|obrigad|parabens|parabéns|denunciar|policia|polícia"
    r")\b",
    re.IGNORECASE,
)

_ES_STRONG = re.compile(
    r"\b("
    r"mujer|mujeres|hombre|hombres|también|tambien|está|esta|están|estan|"
    r"niño|niña|niños|niñas|qué|que|porque|usted|ustedes|señor|señora|"
    r"violencia|acoso|denuncia|justicia|vergüenza|verguenza|ningún|ningun|"
    r"algún|algun|está|había|habia|también|señal|niñas|chicas"
    r")\b",
    re.IGNORECASE,
)

_EN_STRONG = re.compile(
    r"\b("
    r"the|and|you|your|woman|women|man|men|don't|dont|can't|cant|really|please|"
    r"this|that|with|have|from|they|what|when|where|why|how|send|post|shot|"
    r"great|love|nice|check|follow|profile|comment|comments|people|think|"
    r"about|would|should|could|been|being|their|there|these|those"
    r")\b",
    re.IGNORECASE,
)

MIN_LANGDETECT_CHARS = 30
MIN_LETTERS = 10
LETTER_RE = re.compile(r"[a-záéíóúüñãõâêôç]", re.IGNORECASE)


def is_emoji_only_text(text: str) -> bool:
    """True si el texto no tiene letras y contiene al menos un emoji."""
    raw = str(text or "").strip()
    if not raw:
        return False
    if LETTER_RE.search(raw):
        return False
    without_emoji = EMOJI_PATTERN.sub("", raw)
    without_noise = re.sub(r"[\s\d\W_]+", "", without_emoji, flags=re.UNICODE)
    if without_noise:
        return False
    return bool(EMOJI_PATTERN.search(raw))


def _normalize_for_detection(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = EMOJI_PATTERN.sub(" ", value)
    value = re.sub(r"https?://\S+|www\.\S+", " ", value)
    value = re.sub(r"@\w+", " ", value)
    value = re.sub(r"#[\w\u00C0-\u024F]+", " ", value)
    value = re.sub(r"[^\w\sáéíóúüñãõâêôçÁÉÍÓÚÜÑÃÕÂÊÔÇ]", " ", value)
    return re.sub(r"\s+", " ", value).strip().lower()


def _letter_count(text: str) -> int:
    return len(re.sub(r"[^a-záéíóúüñãõâêôç]", "", text, flags=re.IGNORECASE))


def _emoji_ratio(raw: str) -> float:
    if not raw:
        return 0.0
    emoji_chars = len(EMOJI_PATTERN.findall(raw))
    emoji_len = sum(len(e) for e in EMOJI_PATTERN.findall(raw))
    total = len(raw.strip())
    if total == 0:
        return 0.0
    return emoji_len / total


def _heuristic_scores(text: str) -> dict[str, float]:
    pt = len(_PT_STRONG.findall(text)) * 2.0
    es = len(_ES_STRONG.findall(text)) * 2.0
    en = len(_EN_STRONG.findall(text)) * 2.0

    # Señales ortográficas.
    pt += len(re.findall(r"[ãõâêô]", text)) * 1.5
    es += len(re.findall(r"[ñ¿¡]", text)) * 2.0
    en += len(re.findall(r"\b(i'm|you're|don't|won't|it's|that's)\b", text)) * 2.0

    total = pt + es + en
    if total == 0:
        return {"es": 0.0, "pt": 0.0, "en": 0.0}
    return {
        "es": es / total,
        "pt": pt / total,
        "en": en / total,
    }


def _langdetect_scores(text: str) -> dict[str, float]:
    try:
        candidates = detect_langs(text)
    except LangDetectException:
        return {}
    scores: dict[str, float] = {}
    for item in candidates:
        code = item.lang.split("-")[0].lower()
        scores[code] = max(scores.get(code, 0.0), float(item.prob))
    return scores


def detect_language_detailed(text: str) -> tuple[str, float, dict[str, float]]:
    """
    Devuelve (idioma ganador, confianza, scores combinados es/pt/en/...).
    Combina langdetect (sin emojis) + heurística léxica.
    """
    raw = str(text or "")
    if is_emoji_only_text(raw):
        return "emoji", 1.0, {"emoji": 1.0}

    sample = _normalize_for_detection(raw)
    if _letter_count(sample) < MIN_LETTERS:
        return "unknown", 0.0, {}

    heuristic = _heuristic_scores(sample)
    ld_scores = _langdetect_scores(sample) if len(sample) >= MIN_LANGDETECT_CHARS else {}

    combined: dict[str, float] = {}
    for code in {"es", "pt", "en"}:
        combined[code] = (
            ld_scores.get(code, 0.0) * 0.55
            + heuristic.get(code, 0.0) * 0.45
        )

    # Penalizar detección cuando hay muchos emojis y poco texto.
    if _emoji_ratio(raw) > 0.35 and len(sample) < 50:
        for code in combined:
            combined[code] *= 0.6

    if not combined or max(combined.values()) <= 0:
        return "unknown", 0.0, combined

    ranked = sorted(combined.items(), key=lambda item: item[1], reverse=True)
    winner, score = ranked[0]
    return winner, round(score, 3), combined


def detect_language(text: str) -> tuple[str, float]:
    lang, conf, _ = detect_language_detailed(text)
    return lang, conf


def parse_languages_arg(value: str) -> list[str] | None:
    text = str(value or "").strip().lower()
    if not text or text == "all":
        return None
    return [part.strip() for part in text.split(",") if part.strip()]


def language_allowed(
    language: str,
    confidence: float,
    scores: dict[str, float],
    *,
    allowed: list[str] | None,
    min_confidence: float,
    min_margin: float,
    keep_unknown: bool,
) -> bool:
    if allowed is None:
        return True

    lang = (language or "unknown").lower()
    allowed_set = {code.lower() for code in allowed}

    if lang == "unknown":
        return keep_unknown

    if lang == "emoji":
        if allowed_set and "emoji" not in allowed_set:
            return False
        return True

    if lang not in allowed_set:
        return False

    if confidence < min_confidence:
        return False

    if scores:
        ranked = sorted(scores.values(), reverse=True)
        if len(ranked) >= 2 and (ranked[0] - ranked[1]) < min_margin:
            return False

    # Si pedimos español, rechazar si PT supera claramente a ES en heurística.
    if "es" in allowed_set and lang == "es" and scores:
        if scores.get("pt", 0.0) > scores.get("es", 0.0) + 0.08:
            return False

    return True


def filter_comments_by_language(
    comments_df: pd.DataFrame,
    *,
    languages: list[str] | None,
    min_confidence: float = 0.72,
    min_margin: float = 0.12,
    keep_unknown: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Prefiltra comments.csv; devuelve (conservados, excluidos)."""
    if comments_df.empty:
        return comments_df, pd.DataFrame(
            columns=[
                "comment_id",
                "post_id",
                "language",
                "language_confidence",
                "language_scores",
                "comment_text",
                "exclusion_reason",
            ]
        )

    kept_rows: list[dict] = []
    excluded_rows: list[dict] = []

    for _, row in comments_df.iterrows():
        text = str(row.get("comment_text", "") or "").strip()
        if not text:
            continue

        lang, conf, scores = detect_language_detailed(text)
        score_str = ";".join(f"{k}:{v:.2f}" for k, v in sorted(scores.items()))

        if language_allowed(
            lang,
            conf,
            scores,
            allowed=languages,
            min_confidence=min_confidence,
            min_margin=min_margin,
            keep_unknown=keep_unknown,
        ):
            out = row.to_dict()
            out["language"] = lang
            out["language_confidence"] = str(conf)
            out["language_scores"] = score_str
            kept_rows.append(out)
        else:
            reason = "language_filter"
            if lang == "unknown":
                reason = "unknown_language"
            elif lang == "emoji":
                reason = "emoji_only"
            elif languages and lang not in {c.lower() for c in languages}:
                reason = f"not_{languages[0]}"
            elif conf < min_confidence:
                reason = "low_confidence"
            elif scores:
                ranked = sorted(scores.values(), reverse=True)
                if len(ranked) >= 2 and (ranked[0] - ranked[1]) < min_margin:
                    reason = "ambiguous_language"

            excluded_rows.append(
                {
                    "comment_id": str(row.get("comment_id", "")),
                    "post_id": str(row.get("post_id", "")),
                    "language": lang,
                    "language_confidence": str(conf),
                    "language_scores": score_str,
                    "comment_text": text[:400],
                    "exclusion_reason": reason,
                }
            )

    kept = pd.DataFrame(kept_rows)
    excluded = pd.DataFrame(excluded_rows)
    return kept, excluded
