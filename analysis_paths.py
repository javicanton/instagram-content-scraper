"""Rutas de salida del análisis con sufijo de corpus (p. ej. clusters_summary_violencia.csv)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GENERIC_DIR_NAMES = frozenset({"", "analysis", "output", "data"})


def _slug(value: str) -> str:
    text = re.sub(r"[^\w\-]+", "_", str(value or "").strip().lower())
    return text.strip("_") or "corpus"


def resolve_corpus_id(
    *,
    output_dir: Path,
    input_dir: Path | None = None,
    explicit: str = "",
) -> str:
    """Deriva el sufijo del corpus desde --corpus-id, output-dir o input-dir."""
    if str(explicit or "").strip():
        return _slug(explicit)
    out_name = output_dir.name.strip()
    if out_name.lower() not in GENERIC_DIR_NAMES:
        return _slug(out_name)
    if input_dir is not None:
        in_name = input_dir.name.strip()
        if in_name.lower() not in GENERIC_DIR_NAMES:
            return _slug(in_name)
    return "corpus"


@dataclass(frozen=True)
class AnalysisPaths:
    output_dir: Path
    corpus_id: str

    def file(self, stem: str, ext: str = "csv") -> Path:
        return self.output_dir / f"{stem}_{self.corpus_id}.{ext}"

    def read(self, stem: str, ext: str = "csv") -> Path:
        """Preferir archivo con sufijo; fallback al nombre legacy sin sufijo."""
        suffixed = self.file(stem, ext)
        if suffixed.exists():
            return suffixed
        legacy = self.output_dir / f"{stem}.{ext}"
        if legacy.exists():
            return legacy
        return suffixed

    @property
    def comments_for_analysis(self) -> Path:
        return self.file("comments_for_analysis")

    @property
    def language_excluded(self) -> Path:
        return self.file("language_excluded")

    @property
    def language_summary(self) -> Path:
        return self.file("language_summary")

    @property
    def comments_enriched(self) -> Path:
        return self.file("comments_enriched")

    @property
    def discourse_stance_summary(self) -> Path:
        return self.file("discourse_stance_summary")

    @property
    def comments_clustered(self) -> Path:
        return self.file("comments_clustered")

    @property
    def clusters_summary(self) -> Path:
        return self.file("clusters_summary")

    @property
    def sentiment_summary(self) -> Path:
        return self.file("sentiment_summary")

    @property
    def sentiment_by_language(self) -> Path:
        return self.file("sentiment_by_language")

    @property
    def sentiment_by_cluster(self) -> Path:
        return self.file("sentiment_by_cluster")

    @property
    def cluster_labels(self) -> Path:
        return self.file("cluster_labels")

    @property
    def discourse_taxonomy(self) -> Path:
        return self.file("discourse_taxonomy", "json")

    @property
    def discourse_lexicon(self) -> Path:
        return self.file("discourse_lexicon", "json")

    @property
    def posts_discourse(self) -> Path:
        return self.file("posts_discourse")

    @property
    def discourse_category_summary(self) -> Path:
        return self.file("discourse_category_summary")

    @property
    def nodes(self) -> Path:
        return self.file("nodes")

    @property
    def edges_all(self) -> Path:
        return self.file("edges_all")

    @property
    def edges_social(self) -> Path:
        return self.file("edges_social")

    @property
    def edges_narrative(self) -> Path:
        return self.file("edges_narrative")

    @property
    def edges_hashtags(self) -> Path:
        return self.file("edges_hashtags")

    @property
    def edges_users(self) -> Path:
        return self.file("edges_users")

    @property
    def graph(self) -> Path:
        return self.file("graph", "graphml")

    @property
    def graph_hashtags(self) -> Path:
        return self.file("graph_hashtags", "graphml")

    @property
    def graph_users(self) -> Path:
        return self.file("graph_users", "graphml")

    @property
    def network_metrics(self) -> Path:
        return self.file("network_metrics")
