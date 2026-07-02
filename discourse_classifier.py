"""Clasificación léxica de discurso en comentarios (español)."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DEFAULT_LEXICON_PATH = Path(__file__).resolve().parent / "discourse_lexicon.json"
URL_RE = re.compile(r"https?://\S+|www\.\S+")
MULTISPACE_RE = re.compile(r"\s+")

LEGITIMIZATION_LABELS = (
    "legitimacion_trivializacion",
    "legitimacion_culpabilizacion",
    "legitimacion_victimismo_masculino",
    "legitimacion_tecnologica",
    "legitimacion_negacion_violencia",
)


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


def _legacy_to_categories(data: dict) -> list[dict]:
    categories: list[dict] = []
    legitimization_raw = data.get("legitimization", {})
    if isinstance(legitimization_raw, dict):
        for idx, label in enumerate(LEGITIMIZATION_LABELS):
            terms = legitimization_raw.get(label, [])
            categories.append(
                {
                    "id": label,
                    "label": label,
                    "priority": idx + 1,
                    "terms": terms,
                }
            )
    categories.append(
        {
            "id": "feminist",
            "label": "feminist",
            "priority": 20,
            "terms": data.get("feminist", []),
        }
    )
    categories.append(
        {
            "id": "antifeminist",
            "label": "antifeminist",
            "priority": 21,
            "terms": data.get("antifeminist", []),
        }
    )
    categories.append(
        {
            "id": "neutral",
            "label": "neutral",
            "priority": 99,
            "terms": [],
        }
    )
    return categories


def _normalize_categories(raw_categories: list | dict) -> list[dict]:
    if isinstance(raw_categories, dict):
        items = []
        for key, value in raw_categories.items():
            if isinstance(value, dict):
                items.append({"id": key, **value})
            else:
                items.append({"id": key, "label": str(value), "terms": []})
        raw_categories = items

    categories: list[dict] = []
    for item in raw_categories:
        category_id = str(item.get("id", "")).strip()
        if not category_id:
            continue
        terms = [
            _normalize_text(term)
            for term in item.get("terms", [])
            if str(term).strip()
        ]
        categories.append(
            {
                "id": category_id,
                "label": str(item.get("label", category_id)),
                "description": str(item.get("description", "")),
                "priority": int(item.get("priority", 50)),
                "terms": terms,
            }
        )
    categories.sort(key=lambda item: (item["priority"], item["id"]))
    return categories


def build_lexicon_from_taxonomy(
    taxonomy: dict,
    *,
    extra_terms: dict[str, list[str]] | None = None,
) -> dict:
    """Convierte discourse_taxonomy.json en léxico clasificable."""
    categories = _normalize_categories(taxonomy.get("categories", []))
    merged: list[dict] = []
    extra_terms = extra_terms or {}

    for category in categories:
        terms = list(category["terms"])
        for term in extra_terms.get(category["id"], []):
            normalized = _normalize_text(term)
            if normalized and normalized not in terms:
                terms.append(normalized)
        merged.append({**category, "terms": terms})

    return {
        "version": taxonomy.get("version", 1),
        "source": "discourse_taxonomy",
        "categories": merged,
    }


def save_lexicon(lexicon: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lexicon, ensure_ascii=False, indent=2), encoding="utf-8")


def reload_lexicon(path: Path | None = None) -> None:
    _load_lexicon_data.cache_clear()
    if path is not None:
        _load_lexicon_data(path)


@lru_cache(maxsize=8)
def _load_lexicon_data(path_str: str) -> dict:
    path = Path(path_str)
    if not path.exists():
        return {"categories": _normalize_categories([])}

    data = json.loads(path.read_text(encoding="utf-8"))
    if "categories" in data:
        return {"categories": _normalize_categories(data["categories"])}

    return {"categories": _normalize_categories(_legacy_to_categories(data))}


def _resolve_lexicon_path(lexicon_path: Path | None) -> Path:
    return lexicon_path or DEFAULT_LEXICON_PATH


def _match_category(cleaned: str, categories: list[dict]) -> tuple[str, str, list[str], float, float]:
    signals: list[str] = []
    fem_score = 0.0
    anti_score = 0.0

    for category in categories:
        category_id = category["id"]
        if category_id == "neutral":
            continue
        for phrase in category["terms"]:
            if not _phrase_matches(cleaned, phrase):
                continue
            signals.append(f"+{category_id}:{phrase}")
            if category_id == "feminist":
                fem_score += 1
            elif category_id == "antifeminist":
                anti_score += 1
            else:
                return category_id, str(category.get("label", category_id)), signals, fem_score, anti_score

    if fem_score > 0 and anti_score > 0:
        return "mixed", "mixed", signals, fem_score, anti_score
    if fem_score > anti_score:
        return "feminist", "feminist", signals, fem_score, anti_score
    if anti_score > fem_score:
        return "antifeminist", "antifeminist", signals, fem_score, anti_score
    return "neutral", "neutral", signals, fem_score, anti_score


def classify_discourse(
    text: str,
    *,
    lexicon_path: Path | None = None,
) -> dict[str, str | float]:
    """Clasifica un texto con el léxico indicado (prioridad por categoría)."""
    cleaned = _normalize_text(text)
    if not cleaned:
        return {
            "discourse_label": "unlabeled",
            "discourse_stance": "unlabeled",
            "discourse_score_feminist": 0.0,
            "discourse_score_antifeminist": 0.0,
            "discourse_signals": "",
        }

    path = _resolve_lexicon_path(lexicon_path)
    categories = _load_lexicon_data(str(path.resolve()))["categories"]
    label, human_label, signals, fem_score, anti_score = _match_category(cleaned, categories)

    return {
        "discourse_label": label,
        "discourse_stance": label,
        "discourse_category_label": human_label,
        "discourse_score_feminist": fem_score,
        "discourse_score_antifeminist": anti_score,
        "discourse_signals": ";".join(signals[:20]),
    }
