"""Carga de configuración multi-corpus desde YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_CORPORA_CONFIG = PROJECT_ROOT / "corpora.yaml"
EXAMPLE_CORPORA_CONFIG = PROJECT_ROOT / "corpora.example.yaml"


@dataclass(frozen=True)
class CorpusConfig:
    id: str
    hashtags_file: Path
    description: str = ""


def load_corpora_config(path: Path | None = None) -> list[CorpusConfig]:
    """Lee corpora.yaml (o corpora.example.yaml si no existe el primero)."""
    config_path = path or DEFAULT_CORPORA_CONFIG
    if not config_path.exists():
        if path is None and EXAMPLE_CORPORA_CONFIG.exists():
            config_path = EXAMPLE_CORPORA_CONFIG
        else:
            raise FileNotFoundError(
                f"No se encontró {config_path}. "
                f"Copia corpora.example.yaml → corpora.yaml y edita tus listas."
            )

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    items = data.get("corpora", [])
    if not items:
        raise ValueError(f"Sin entradas 'corpora' en {config_path}")

    corpora: list[CorpusConfig] = []
    for item in items:
        corpus_id = str(item.get("id", "")).strip()
        hashtags_raw = str(item.get("hashtags_file", "")).strip()
        if not corpus_id or not hashtags_raw:
            raise ValueError(f"Entrada inválida en {config_path}: {item}")
        hashtags_path = Path(hashtags_raw)
        if not hashtags_path.is_absolute():
            hashtags_path = (config_path.parent / hashtags_path).resolve()
        corpora.append(
            CorpusConfig(
                id=corpus_id,
                hashtags_file=hashtags_path,
                description=str(item.get("description", "") or ""),
            )
        )
    return corpora
