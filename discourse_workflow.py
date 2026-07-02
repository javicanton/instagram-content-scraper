"""Flujo de clasificación de discurso guiado por clustering + taxonomía manual."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from analysis_paths import AnalysisPaths
from discourse_classifier import (
    build_lexicon_from_taxonomy,
    classify_discourse,
    reload_lexicon,
    save_lexicon,
)


def _truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "si", "sí", "y"}


def load_taxonomy(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"No se encontró la taxonomía: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    categories = data.get("categories", [])
    if isinstance(categories, dict):
        categories = [
            {"id": key, **(value if isinstance(value, dict) else {"label": str(value)})}
            for key, value in categories.items()
        ]
    data["categories"] = categories
    return data


def load_cluster_labels(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No se encontró {path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")


def category_lookup(taxonomy: dict) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for item in taxonomy.get("categories", []):
        cid = str(item.get("id", "")).strip()
        if cid:
            lookup[cid] = item
    return lookup


def export_labeling_templates(
    paths: AnalysisPaths,
    *,
    overwrite: bool = False,
) -> tuple[Path, Path]:
    """Genera plantillas editables a partir de clusters_summary_<corpus>.csv."""
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = paths.read("clusters_summary")
    if not summary_path.exists():
        raise FileNotFoundError(
            f"Falta {summary_path}. Ejecuta antes: python analyze.py --step cluster ..."
        )

    summary = pd.read_csv(summary_path, dtype=str, keep_default_na=False, encoding="utf-8")
    labels_path = paths.cluster_labels
    taxonomy_path = paths.discourse_taxonomy

    if not labels_path.exists() or overwrite:
        rows = []
        for _, row in summary.iterrows():
            rows.append(
                {
                    "cluster_id": str(row.get("cluster_id", "")),
                    "n_comments": str(row.get("n_comments", "")),
                    "top_terms": str(row.get("top_terms", "")),
                    "representative_comments": str(row.get("representative_comments", ""))[:400],
                    "discourse_category_id": "",
                    "reviewed": "",
                    "notes": "",
                }
            )
        pd.DataFrame(rows).to_csv(labels_path, index=False, encoding="utf-8")

    if not taxonomy_path.exists() or overwrite:
        example = Path(__file__).resolve().parent / "discourse_taxonomy.example.json"
        if example.exists():
            shutil.copy(example, taxonomy_path)
        else:
            taxonomy_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "notes": "Define categorías tras revisar clusters_summary",
                        "categories": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    return labels_path, taxonomy_path


def bootstrap_lexicon_for_corpus(
    paths: AnalysisPaths,
    *,
    include_cluster_terms: bool = True,
    min_term_length: int = 3,
) -> Path:
    """Construye discourse_lexicon_<corpus>.json desde taxonomía + términos de cluster."""
    taxonomy = load_taxonomy(paths.discourse_taxonomy)
    labels_df = load_cluster_labels(paths.cluster_labels)
    summary_df = pd.read_csv(
        paths.read("clusters_summary"),
        dtype=str,
        keep_default_na=False,
        encoding="utf-8",
    )
    summary_by_cluster = {
        str(row["cluster_id"]): row for _, row in summary_df.iterrows()
    }

    extra_terms: dict[str, list[str]] = {}
    if include_cluster_terms:
        for _, row in labels_df.iterrows():
            category_id = str(row.get("discourse_category_id", "")).strip()
            if not category_id or not _truthy(row.get("reviewed", "")):
                continue
            cluster_id = str(row.get("cluster_id", "")).strip()
            summary_row = summary_by_cluster.get(cluster_id, row)
            terms_blob = str(summary_row.get("top_terms", "") or row.get("top_terms", ""))
            terms = [
                t.strip()
                for t in terms_blob.replace("|", ";").split(";")
                if len(t.strip()) >= min_term_length
            ]
            extra_terms.setdefault(category_id, []).extend(terms)

    lexicon = build_lexicon_from_taxonomy(taxonomy, extra_terms=extra_terms)
    save_lexicon(lexicon, paths.discourse_lexicon)
    reload_lexicon(paths.discourse_lexicon)
    return paths.discourse_lexicon


def apply_cluster_labels(
    clustered_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    taxonomy: dict,
) -> pd.DataFrame:
    """Asigna discourse_category_* desde cluster_labels.csv revisado."""
    lookup = category_lookup(taxonomy)
    mapping: dict[str, tuple[str, str]] = {}
    for _, row in labels_df.iterrows():
        if not _truthy(row.get("reviewed", "")):
            continue
        cluster_id = str(row.get("cluster_id", "")).strip()
        category_id = str(row.get("discourse_category_id", "")).strip()
        if not cluster_id or not category_id:
            continue
        category = lookup.get(category_id, {})
        mapping[cluster_id] = (
            category_id,
            str(category.get("label", category_id)),
        )

    out = clustered_df.copy()
    out["discourse_category_id"] = ""
    out["discourse_category_label"] = ""
    out["discourse_source"] = "unlabeled"

    for idx, row in out.iterrows():
        cluster_id = str(row.get("cluster_id", "")).strip()
        if cluster_id in mapping:
            cat_id, cat_label = mapping[cluster_id]
            out.at[idx, "discourse_category_id"] = cat_id
            out.at[idx, "discourse_category_label"] = cat_label
            out.at[idx, "discourse_label"] = cat_id
            out.at[idx, "discourse_stance"] = cat_id
            out.at[idx, "discourse_source"] = "cluster"

    return out


def relabel_with_lexicon(
    df: pd.DataFrame,
    *,
    lexicon_path: Path,
    text_column: str = "comment_text",
    only_unlabeled: bool = True,
) -> pd.DataFrame:
    """Re-etiqueta filas con el léxico del corpus (sin pisar etiquetas de cluster)."""
    reload_lexicon(lexicon_path)
    out = df.copy()
    for idx, row in out.iterrows():
        if only_unlabeled and str(row.get("discourse_source", "")) == "cluster":
            continue
        text = str(row.get(text_column, "") or "")
        if not text.strip():
            continue
        result = classify_discourse(text, lexicon_path=lexicon_path)
        label = str(result.get("discourse_label", "") or "")
        if label in {"", "neutral", "unlabeled"}:
            continue
        out.at[idx, "discourse_label"] = label
        out.at[idx, "discourse_stance"] = label
        out.at[idx, "discourse_category_id"] = label
        out.at[idx, "discourse_category_label"] = label
        out.at[idx, "discourse_score_feminist"] = str(result.get("discourse_score_feminist", ""))
        out.at[idx, "discourse_score_antifeminist"] = str(
            result.get("discourse_score_antifeminist", "")
        )
        out.at[idx, "discourse_signals"] = str(result.get("discourse_signals", ""))
        out.at[idx, "discourse_source"] = "lexical"

    return out


def update_clusters_summary(
    summary_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    taxonomy: dict,
) -> pd.DataFrame:
    lookup = category_lookup(taxonomy)
    label_map = {
        str(row["cluster_id"]).strip(): str(row.get("discourse_category_id", "")).strip()
        for _, row in labels_df.iterrows()
        if _truthy(row.get("reviewed", ""))
    }

    out = summary_df.copy()
    if "discourse_category_id" not in out.columns:
        out["discourse_category_id"] = ""
    if "discourse_category_label" not in out.columns:
        out["discourse_category_label"] = ""

    for idx, row in out.iterrows():
        cluster_id = str(row.get("cluster_id", "")).strip()
        category_id = label_map.get(cluster_id, "")
        if not category_id:
            continue
        category = lookup.get(category_id, {})
        out.at[idx, "discourse_category_id"] = category_id
        out.at[idx, "discourse_category_label"] = str(category.get("label", category_id))
        out.at[idx, "narrative_label"] = str(category.get("label", category_id))

    return out


def label_posts_from_comments(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    *,
    lexicon_path: Path | None = None,
) -> pd.DataFrame:
    """Etiqueta posts por discurso dominante en comentarios y léxico en caption."""
    if posts_df.empty:
        return pd.DataFrame()

    comment_groups = {}
    if not comments_df.empty and "post_id" in comments_df.columns:
        labeled = comments_df[
            comments_df.get("discourse_category_id", pd.Series(dtype=str))
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
        ]
        for post_id, group in labeled.groupby("post_id"):
            counts = group["discourse_category_id"].value_counts()
            if counts.empty:
                continue
            top_id = str(counts.index[0])
            top_label = ""
            if "discourse_category_label" in group.columns:
                match = group[group["discourse_category_id"] == top_id]
                if not match.empty:
                    top_label = str(match.iloc[0].get("discourse_category_label", top_id))
            comment_groups[str(post_id)] = {
                "discourse_category_id": top_id,
                "discourse_category_label": top_label or top_id,
                "comment_label_counts": counts.to_dict(),
                "n_labeled_comments": len(group),
            }

    rows: list[dict] = []
    for _, post in posts_df.iterrows():
        post_id = str(post.get("post_id", ""))
        caption = str(post.get("caption", "") or "")
        caption_result = (
            classify_discourse(caption, lexicon_path=lexicon_path)
            if caption.strip() and lexicon_path
            else {}
        )
        comment_info = comment_groups.get(post_id, {})
        rows.append(
            {
                "post_id": post_id,
                "profile_username": str(post.get("profile_username", "") or ""),
                "source_hashtag": str(post.get("source_hashtag", "") or ""),
                "caption_discourse_label": str(caption_result.get("discourse_label", "unlabeled")),
                "caption_discourse_signals": str(caption_result.get("discourse_signals", "")),
                "dominant_comment_category_id": comment_info.get("discourse_category_id", ""),
                "dominant_comment_category_label": comment_info.get("discourse_category_label", ""),
                "comment_label_counts": str(comment_info.get("comment_label_counts", "")),
                "n_labeled_comments": str(comment_info.get("n_labeled_comments", "0")),
                "post_discourse_label": comment_info.get("discourse_category_id")
                or str(caption_result.get("discourse_label", "unlabeled")),
            }
        )

    return pd.DataFrame(rows)


def apply_discourse_workflow(
    paths: AnalysisPaths,
    input_dir: Path,
    *,
    bootstrap_lexicon: bool = True,
    relabel_lexical: bool = True,
    label_posts: bool = True,
) -> dict[str, Path]:
    """Aplica taxonomía + cluster_labels, retroalimenta léxico y re-etiqueta."""
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    clustered_path = paths.read("comments_clustered")
    if not clustered_path.exists():
        raise FileNotFoundError(
            f"Falta {clustered_path}. Ejecuta clustering y luego discourse-init."
        )

    taxonomy_path = paths.read("discourse_taxonomy", "json")
    if not taxonomy_path.exists():
        taxonomy_path = paths.discourse_taxonomy
    labels_path = paths.read("cluster_labels")
    if not labels_path.exists():
        labels_path = paths.cluster_labels

    taxonomy = load_taxonomy(taxonomy_path)
    labels_df = load_cluster_labels(labels_path)
    if taxonomy.get("categories") and labels_df[
        labels_df["discourse_category_id"].astype(str).str.strip().ne("")
    ].empty:
        raise ValueError(
            f"Completa {labels_path} (discourse_category_id + reviewed=yes) "
            f"y define categorías en {taxonomy_path}."
        )

    clustered = pd.read_csv(clustered_path, dtype=str, keep_default_na=False, encoding="utf-8")
    labeled = apply_cluster_labels(clustered, labels_df, taxonomy)

    lexicon_path = paths.discourse_lexicon
    if bootstrap_lexicon:
        lexicon_path = bootstrap_lexicon_for_corpus(paths)

    if relabel_lexical and lexicon_path.exists():
        labeled = relabel_with_lexicon(labeled, lexicon_path=lexicon_path, only_unlabeled=True)

    labeled.to_csv(paths.comments_clustered, index=False, encoding="utf-8")
    labeled.to_csv(paths.comments_enriched, index=False, encoding="utf-8")

    summary_path = paths.read("clusters_summary")
    if summary_path.exists():
        summary = pd.read_csv(summary_path, dtype=str, keep_default_na=False, encoding="utf-8")
        summary = update_clusters_summary(summary, labels_df, taxonomy)
        summary.to_csv(paths.clusters_summary, index=False, encoding="utf-8")
        summary_path = paths.clusters_summary

    outputs: dict[str, Path] = {
        "comments_clustered": paths.comments_clustered,
        "comments_enriched": paths.comments_enriched,
        "clusters_summary": summary_path,
        "lexicon": lexicon_path,
    }

    if not labeled.empty:
        summary_counts = (
            labeled[labeled["discourse_category_id"].astype(str).str.strip().ne("")]
            .groupby(["discourse_category_id", "discourse_category_label"])
            .size()
            .reset_index(name="count")
        )
        summary_counts.to_csv(paths.discourse_category_summary, index=False, encoding="utf-8")
        outputs["discourse_summary"] = paths.discourse_category_summary

    posts_path = input_dir / "posts.csv"
    if label_posts and posts_path.exists():
        posts_df = pd.read_csv(posts_path, dtype=str, keep_default_na=False, encoding="utf-8")
        posts_discourse = label_posts_from_comments(
            posts_df,
            labeled,
            lexicon_path=lexicon_path if lexicon_path.exists() else None,
        )
        posts_discourse.to_csv(paths.posts_discourse, index=False, encoding="utf-8")
        outputs["posts_discourse"] = paths.posts_discourse

    return outputs
