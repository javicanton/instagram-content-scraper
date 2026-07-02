"""Clustering de comentarios para detectar narrativas."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from nlp_stopwords import STOPWORDS
from text_prep import prepare_text_for_clustering


@dataclass
class ClusteringResult:
    enriched: pd.DataFrame
    summary: pd.DataFrame
    n_clusters: int


def _auto_k(n_docs: int, requested: int | None) -> int:
    if requested and requested > 0:
        return min(requested, max(2, n_docs // 5))
    if n_docs < 30:
        return max(2, min(5, n_docs // 5 or 2))
    if n_docs < 200:
        return 8
    return 12


def _clustering_texts(enriched_df: pd.DataFrame) -> list[str]:
    if "comment_text_cluster" in enriched_df.columns:
        series = enriched_df["comment_text_cluster"].fillna("")
    else:
        series = enriched_df.get("comment_text_clean", pd.Series(dtype=str)).fillna("")

    texts: list[str] = []
    lang_series = enriched_df.get("language", pd.Series(dtype=str))
    for raw, fallback, lang in zip(
        series.tolist(),
        enriched_df["comment_text"].fillna(""),
        lang_series.fillna(""),
    ):
        text = str(raw).strip()
        if not text:
            text = prepare_text_for_clustering(str(fallback), language=str(lang))
        texts.append(text)
    return texts


def _build_vectorizer(max_features: int) -> TfidfVectorizer:
    return TfidfVectorizer(
        max_features=max_features,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.85,
        strip_accents="unicode",
        stop_words=list(STOPWORDS),
        token_pattern=r"(?u)\b[\wáéíóúüñãõç]{3,}\b",
        sublinear_tf=True,
    )


def _is_meaningful_term(term: str) -> bool:
    if not term or term in STOPWORDS:
        return False
    parts = term.split()
    if all(part in STOPWORDS for part in parts):
        return False
    if len(term) < 3:
        return False
    return True


def _top_terms_per_cluster(
    vectorizer: TfidfVectorizer,
    labels: list[int],
    texts: list[str],
    top_n: int = 12,
) -> dict[int, str]:
    matrix = vectorizer.transform(texts)
    feature_names = vectorizer.get_feature_names_out()
    cluster_terms: dict[int, str] = {}

    for cluster_id in sorted(set(labels)):
        indices = [i for i, label in enumerate(labels) if label == cluster_id]
        if not indices:
            cluster_terms[cluster_id] = ""
            continue
        submatrix = matrix[indices].mean(axis=0)
        scores = submatrix.A1 if hasattr(submatrix, "A1") else submatrix.toarray()[0]
        ranked = sorted(
            zip(feature_names, scores),
            key=lambda x: x[1],
            reverse=True,
        )
        terms: list[str] = []
        for term, score in ranked:
            if score <= 0 or not _is_meaningful_term(term):
                continue
            terms.append(term)
            if len(terms) >= top_n:
                break
        cluster_terms[cluster_id] = "; ".join(terms)

    return cluster_terms


def _representative_comments(
    enriched: pd.DataFrame,
    labels: list[int],
    matrix,
    top_n: int = 3,
) -> dict[int, str]:
    reps: dict[int, str] = {}
    work = enriched.copy()
    work["cluster_id"] = labels

    for cluster_id in sorted(set(labels)):
        indices = [i for i, label in enumerate(labels) if label == cluster_id]
        if not indices:
            reps[cluster_id] = ""
            continue

        submatrix = matrix[indices]
        if hasattr(submatrix, "toarray"):
            submatrix = submatrix.toarray()
        centroid = np.asarray(submatrix.mean(axis=0))
        sims = cosine_similarity(submatrix, centroid.reshape(1, -1)).ravel()
        order = np.argsort(-sims)

        samples: list[str] = []
        for pos in order[:top_n]:
            text = str(work.iloc[indices[pos]]["comment_text"])
            samples.append(text.replace("\n", " ")[:200])
        reps[cluster_id] = " || ".join(samples)

    return reps


def cluster_comments(
    enriched_df: pd.DataFrame,
    *,
    n_clusters: int | None = None,
    max_features: int = 8000,
) -> ClusteringResult:
    if enriched_df.empty:
        empty = pd.DataFrame(
            columns=list(enriched_df.columns) + ["cluster_id", "narrative_label"]
        )
        return ClusteringResult(
            enriched=empty,
            summary=pd.DataFrame(
                columns=[
                    "cluster_id",
                    "narrative_label",
                    "discourse_category_id",
                    "discourse_category_label",
                    "n_comments",
                    "top_terms",
                    "representative_comments",
                    "top_profiles",
                ]
            ),
            n_clusters=0,
        )

    texts = _clustering_texts(enriched_df)
    usable_mask = [bool(text.strip()) for text in texts]
    if not any(usable_mask):
        raise ValueError("No hay comentarios con tokens útiles tras stopwords.")

    work_df = enriched_df.loc[usable_mask].reset_index(drop=True)
    texts = [text for text, ok in zip(texts, usable_mask) if ok]

    k = _auto_k(len(texts), n_clusters)

    vectorizer = _build_vectorizer(max_features)
    matrix = vectorizer.fit_transform(texts)

    if matrix.shape[0] < k:
        k = max(2, matrix.shape[0] // 2 or 1)

    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = model.fit_predict(matrix).tolist()

    terms = _top_terms_per_cluster(vectorizer, labels, texts)
    reps = _representative_comments(work_df, labels, matrix)

    out = work_df.copy()
    out["cluster_id"] = [str(label) for label in labels]
    out["narrative_label"] = out["cluster_id"].map(lambda cid: f"narrativa_{cid}")
    if "discourse_category_id" not in out.columns:
        out["discourse_category_id"] = ""
    if "discourse_category_label" not in out.columns:
        out["discourse_category_label"] = ""
    if "discourse_source" not in out.columns:
        out["discourse_source"] = "pending"

    profile_counts = (
        out.groupby("cluster_id")["profile_username"]
        .apply(lambda s: "; ".join(s.value_counts().head(5).index.tolist()))
        .to_dict()
    )

    summary_rows = []
    for cluster_id in sorted(set(labels), key=lambda x: int(x)):
        cid = str(cluster_id)
        subset = out[out["cluster_id"] == cid]
        summary_rows.append(
            {
                "cluster_id": cid,
                "narrative_label": f"narrativa_{cid}",
                "discourse_category_id": "",
                "discourse_category_label": "",
                "n_comments": len(subset),
                "top_terms": terms.get(cluster_id, ""),
                "representative_comments": reps.get(cluster_id, ""),
                "top_profiles": profile_counts.get(cid, ""),
            }
        )

    summary = pd.DataFrame(summary_rows)
    return ClusteringResult(enriched=out, summary=summary, n_clusters=k)
