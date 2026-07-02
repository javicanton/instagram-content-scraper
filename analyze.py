#!/usr/bin/env python3
"""CLI de análisis (fase 2): clustering de narrativas y construcción de grafos."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from analysis_paths import AnalysisPaths, resolve_corpus_id
from clustering import cluster_comments
from discourse_workflow import apply_discourse_workflow, export_labeling_templates
from graph_builder import (
    build_full_graph,
    build_hashtag_nodes,
    build_user_network_nodes,
    export_graphml,
)
from language_detect import filter_comments_by_language, parse_languages_arg
from network_metrics import export_network_metrics
from sentiment import (
    add_sentiment_columns,
    append_sentiment_to_cluster_summary,
    summarize_sentiment,
    write_sentiment_summaries,
)
from text_prep import enrich_comments

PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Análisis de narrativas: clustering de comentarios y grafo de red."
    )
    parser.add_argument(
        "--step",
        choices=["lang", "prep", "cluster", "graph", "discourse-init", "discourse-apply", "all"],
        default="all",
        help=(
            "Paso: lang, prep, cluster, graph, discourse-init, discourse-apply o all. "
            "discourse-init/apply: taxonomía manual tras clustering ciego."
        ),
    )
    parser.add_argument(
        "--input-dir",
        default="data/output",
        help="Directorio con posts.csv y comments.csv del scraper.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/analysis",
        help="Directorio de salida del análisis.",
    )
    parser.add_argument(
        "--corpus-id",
        default="",
        help="Sufijo de archivos de salida (default: nombre de --output-dir o --input-dir).",
    )
    parser.add_argument(
        "--n-clusters",
        type=int,
        default=None,
        help="Número de clusters (auto si se omite).",
    )
    parser.add_argument(
        "--min-comment-length",
        type=int,
        default=15,
        help="Longitud mínima del comentario tras limpieza.",
    )
    parser.add_argument(
        "--min-co-comments",
        type=int,
        default=2,
        help="Mínimo de posts compartidos para aristas co_comment en el grafo.",
    )
    parser.add_argument(
        "--date-from",
        default="",
        help="Filtrar posts con published_at >= YYYY-MM-DD (inclusive).",
    )
    parser.add_argument(
        "--date-to",
        default="",
        help="Filtrar posts con published_at <= YYYY-MM-DD (inclusive).",
    )
    parser.add_argument(
        "--export-metrics",
        action="store_true",
        help="Calcular métricas de red (degree, betweenness, comunidades).",
    )
    parser.add_argument(
        "--languages",
        default="es",
        help=(
            'Idiomas a conservar para prep/cluster (ISO 639-1, separados por coma). '
            'Por defecto "es": solo comentarios en español entran al clustering. '
            'Usa "all" para detectar sin filtrar (mezcla idiomas en clusters).'
        ),
    )
    parser.add_argument(
        "--min-language-confidence",
        type=float,
        default=0.72,
        help="Confianza mínima de detección (0–1). Subir a 0.80–0.85 si queda ruido PT/EN.",
    )
    parser.add_argument(
        "--min-language-margin",
        type=float,
        default=0.12,
        help="Diferencia mínima entre 1.º y 2.º idioma (evita casos ambiguos).",
    )
    parser.add_argument(
        "--keep-unknown-language",
        action="store_true",
        help="Incluir comentarios con idioma no detectado (unknown).",
    )
    parser.add_argument(
        "--overwrite-discourse-templates",
        action="store_true",
        help="Sobrescribe cluster_labels y discourse_taxonomy en discourse-init.",
    )
    return parser.parse_args()


def _parse_date_arg(value: str, *, end_of_day: bool = False) -> datetime | None:
    """Parsea YYYY-MM-DD a datetime UTC."""
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        dt = datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"Fecha inválida '{text}': usa formato YYYY-MM-DD") from exc
    if end_of_day:
        return dt.replace(hour=23, minute=59, second=59)
    return dt


def _parse_published_at(value: str) -> datetime | None:
    """Interpreta published_at ISO o timestamp numérico."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.isdigit():
        ts = int(text)
        if ts > 10_000_000_000:
            ts //= 1000
        return datetime.utcfromtimestamp(ts)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def filter_by_date_range(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    *,
    date_from: str = "",
    date_to: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filtra posts por published_at y conserva solo comentarios de posts restantes."""
    if posts_df.empty or (not date_from and not date_to):
        return posts_df, comments_df

    start = _parse_date_arg(date_from) if date_from else None
    end = _parse_date_arg(date_to, end_of_day=True) if date_to else None

    before_posts = len(posts_df)
    keep_mask = []
    for _, row in posts_df.iterrows():
        published = _parse_published_at(str(row.get("published_at", "")))
        if published is None:
            keep_mask.append(False)
            continue
        ok = True
        if start and published < start:
            ok = False
        if end and published > end:
            ok = False
        keep_mask.append(ok)

    filtered_posts = posts_df[keep_mask].reset_index(drop=True)
    kept_ids = set(filtered_posts["post_id"].astype(str).tolist())
    filtered_comments = comments_df[
        comments_df["post_id"].astype(str).isin(kept_ids)
    ].reset_index(drop=True)

    print(
        f"  Filtro temporal ({date_from or '…'} → {date_to or '…'}): "
        f"{before_posts} → {len(filtered_posts)} posts, "
        f"{len(comments_df)} → {len(filtered_comments)} comentarios"
    )
    return filtered_posts, filtered_comments


def load_scraper_data(input_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    posts_path = input_dir / "posts.csv"
    comments_path = input_dir / "comments.csv"

    if not comments_path.exists():
        raise FileNotFoundError(
            f"No se encontró {comments_path}. Ejecuta primero orchestrator.py."
        )

    posts_df = (
        pd.read_csv(posts_path, dtype=str, keep_default_na=False, encoding="utf-8")
        if posts_path.exists()
        else pd.DataFrame()
    )
    comments_df = pd.read_csv(
        comments_path, dtype=str, keep_default_na=False, encoding="utf-8"
    )
    return posts_df, comments_df


def run_lang_filter(
    comments_df: pd.DataFrame,
    paths: AnalysisPaths,
    *,
    languages: list[str] | None,
    min_language_confidence: float,
    min_language_margin: float,
    keep_unknown_language: bool,
) -> pd.DataFrame:
    """Prefiltra comments.csv por idioma antes del NLP."""
    paths.output_dir.mkdir(parents=True, exist_ok=True)

    with_text = comments_df[
        comments_df["comment_text"].fillna("").astype(str).str.strip().ne("")
    ].copy()
    print(f"  Comentarios con texto: {len(with_text)}")

    kept, excluded = filter_comments_by_language(
        with_text,
        languages=languages,
        min_confidence=min_language_confidence,
        min_margin=min_language_margin,
        keep_unknown=keep_unknown_language,
    )

    if not kept.empty:
        kept = add_sentiment_columns(kept)

    kept.to_csv(paths.comments_for_analysis, index=False, encoding="utf-8")

    if not excluded.empty:
        excluded.to_csv(paths.language_excluded, index=False, encoding="utf-8")
        by_lang = excluded["language"].value_counts().to_dict()
        by_reason = excluded["exclusion_reason"].value_counts().to_dict()
        print(f"  Excluidos: {len(excluded)} → {paths.language_excluded.name}")
        print(f"    por idioma detectado: {by_lang}")
        print(f"    por motivo: {by_reason}")

    if not kept.empty and "language" in kept.columns:
        summary = kept["language"].value_counts().reset_index()
        summary.columns = ["language", "count"]
        summary.to_csv(paths.language_summary, index=False, encoding="utf-8")
        print(f"  Conservados: {len(kept)} → {paths.comments_for_analysis.name}")
        print(f"  Idiomas: {dict(zip(summary['language'], summary['count']))}")
        if "sentiment_label" in kept.columns:
            sent = kept["sentiment_label"].value_counts().to_dict()
            print(f"  Sentimiento: {sent}")
            write_sentiment_summaries(kept, paths)
    else:
        print(f"  Conservados: {len(kept)} → {paths.comments_for_analysis.name}")

    return kept


def run_prep(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    paths: AnalysisPaths,
    min_comment_length: int,
    *,
    languages: list[str] | None,
    min_language_confidence: float,
    min_language_margin: float,
    keep_unknown_language: bool,
) -> pd.DataFrame:
    enriched, excluded = enrich_comments(
        comments_df,
        posts_df,
        min_length=min_comment_length,
        languages=languages,
        min_language_confidence=min_language_confidence,
        min_language_margin=min_language_margin,
        keep_unknown_language=keep_unknown_language,
    )
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(paths.comments_enriched, index=False, encoding="utf-8")

    if not enriched.empty and "language" in enriched.columns:
        lang_summary = enriched["language"].value_counts().reset_index()
        lang_summary.columns = ["language", "count"]
        lang_summary.to_csv(paths.language_summary, index=False, encoding="utf-8")
        print(f"  Idiomas (tras filtro): {dict(zip(lang_summary['language'], lang_summary['count']))}")

    if not excluded.empty:
        excluded.to_csv(paths.language_excluded, index=False, encoding="utf-8")
        print(f"  Excluidos por idioma: {len(excluded)} → {paths.language_excluded.name}")

    label_col = "discourse_category_id" if "discourse_category_id" in enriched.columns else "discourse_label"
    if label_col in enriched.columns and not enriched.empty:
        labeled = enriched[enriched[label_col].fillna("").astype(str).str.strip().ne("")]
        if labeled.empty:
            print("  Discurso: pendiente (usa --step discourse-init tras revisar clusters)")
        else:
            summary = labeled[label_col].value_counts().reset_index()
            summary.columns = ["discourse_label", "count"]
            summary.to_csv(paths.discourse_stance_summary, index=False, encoding="utf-8")
            print(f"  Discurso: {dict(zip(summary['discourse_label'], summary['count']))}")

    if not enriched.empty and "sentiment_label" in enriched.columns:
        sent = enriched["sentiment_label"].value_counts().to_dict()
        print(f"  Sentimiento: {sent}")
        write_sentiment_summaries(enriched, paths)

    print(f"  Comentarios enriquecidos: {len(enriched)} → {paths.comments_enriched.name}")
    if comments_df is not None and not comments_df.empty and enriched.empty:
        raw_with_text = int(
            comments_df.get("comment_text", pd.Series(dtype=str))
            .fillna("")
            .astype(str)
            .str.strip()
            .ne("")
            .sum()
        )
        if raw_with_text == 0:
            print(
                "  AVISO: comments.csv tiene filas pero comment_text está vacío "
                "(scrape anterior con bug). Re-descarga comentarios, por ejemplo:\n"
                "    python orchestrator.py --mode hashtags \\\n"
                "      --hashtag-file examples/hashtags_manosfera.csv \\\n"
                "      --output-dir data/output/manosfera \\\n"
                "      --corpus-id manosfera \\\n"
                "      --repair-posts --resume --with-comments",
                file=sys.stderr,
            )
        else:
            print(
                f"  AVISO: {raw_with_text} comentarios con texto fueron filtrados "
                f"(min_length={min_comment_length}, emojis-only, etc.).",
                file=sys.stderr,
            )
    return enriched


def run_cluster(
    enriched: pd.DataFrame,
    paths: AnalysisPaths,
    n_clusters: int | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    result = cluster_comments(enriched, n_clusters=n_clusters)
    summary = append_sentiment_to_cluster_summary(result.summary, result.enriched)

    result.enriched.to_csv(paths.comments_clustered, index=False, encoding="utf-8")
    summary.to_csv(paths.clusters_summary, index=False, encoding="utf-8")

    if not result.enriched.empty and "sentiment_label" in result.enriched.columns:
        by_cluster = summarize_sentiment(result.enriched, group_col="cluster_id")
        by_cluster.to_csv(paths.sentiment_by_cluster, index=False, encoding="utf-8")
        print(f"  Polarización por cluster → {paths.sentiment_by_cluster.name}")

    print(f"  Clusters: {result.n_clusters}")
    print(f"  Comentarios etiquetados → {paths.comments_clustered.name}")
    print(f"  Resumen narrativas    → {paths.clusters_summary.name}")
    return result.enriched, summary


def run_graph(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    enriched: pd.DataFrame,
    summary: pd.DataFrame,
    paths: AnalysisPaths,
    min_co_comments: int,
    *,
    export_metrics: bool = False,
) -> None:
    nodes, all_edges, social_edges, hashtag_edges, user_network_edges = build_full_graph(
        posts_df,
        comments_df,
        enriched,
        summary,
        min_co_comments=min_co_comments,
    )

    nodes.to_csv(paths.nodes, index=False, encoding="utf-8")
    all_edges.to_csv(paths.edges_all, index=False, encoding="utf-8")
    social_edges.to_csv(paths.edges_social, index=False, encoding="utf-8")
    hashtag_edges.to_csv(paths.edges_hashtags, index=False, encoding="utf-8")
    user_network_edges.to_csv(paths.edges_users, index=False, encoding="utf-8")

    narrative_edges = all_edges[
        all_edges["edge_type"].str.startswith("narrative")
        | all_edges["edge_type"].str.contains("narrative")
    ]
    narrative_edges.to_csv(paths.edges_narrative, index=False, encoding="utf-8")
    export_graphml(nodes, all_edges, paths.graph)

    hashtag_nodes = build_hashtag_nodes(posts_df)
    if not hashtag_nodes.empty and not hashtag_edges.empty:
        hashtag_only = hashtag_edges[
            hashtag_edges["edge_type"] == "hashtag_cooccurrence"
        ]
        export_graphml(hashtag_nodes, hashtag_only, paths.graph_hashtags)

    user_nodes = build_user_network_nodes(posts_df, comments_df, enriched)
    if not user_nodes.empty and not user_network_edges.empty:
        export_graphml(user_nodes, user_network_edges, paths.graph_users)

    if export_metrics:
        metrics_df = export_network_metrics(
            hashtag_nodes,
            hashtag_edges,
            user_network_edges,
            paths.network_metrics,
        )
        print(f"  Métricas de red: {len(metrics_df)} filas → {paths.network_metrics.name}")

    print(f"  Nodos: {len(nodes)} → {paths.nodes.name}")
    print(f"  Aristas totales: {len(all_edges)} → {paths.edges_all.name}")
    print(f"  Grafo hashtags: {paths.graph_hashtags.name}")
    print(f"  Grafo usuarios: {paths.graph_users.name}")
    print(f"  Grafo completo Gephi: {paths.graph.name}")


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    corpus_id = resolve_corpus_id(
        output_dir=output_dir,
        input_dir=input_dir,
        explicit=args.corpus_id,
    )
    paths = AnalysisPaths(output_dir=output_dir, corpus_id=corpus_id)

    try:
        posts_df, comments_df = load_scraper_data(input_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.date_from or args.date_to:
        try:
            posts_df, comments_df = filter_by_date_range(
                posts_df,
                comments_df,
                date_from=args.date_from,
                date_to=args.date_to,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    print(f"Entrada: {len(posts_df)} posts, {len(comments_df)} comentarios")
    print(f"Corpus: {corpus_id} → archivos *_{corpus_id}.* en {output_dir}")

    enriched = pd.DataFrame()
    summary = pd.DataFrame()
    comments_for_analysis = comments_df
    allowed_langs = parse_languages_arg(args.languages)

    if args.step == "discourse-init":
        try:
            labels_path, taxonomy_path = export_labeling_templates(
                paths,
                overwrite=args.overwrite_discourse_templates,
            )
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print("\n=== Plantillas de discurso generadas ===")
        print(f"  1. Revisa {paths.clusters_summary.name}")
        print(f"  2. Edita categorías en {taxonomy_path.name}")
        print(f"  3. Asigna clusters en {labels_path.name} (discourse_category_id + reviewed=yes)")
        print("  4. python analyze.py --step discourse-apply ...")
        return 0

    if args.step == "discourse-apply":
        try:
            outputs = apply_discourse_workflow(paths, input_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print("\n=== Discurso aplicado ===")
        for name, path in outputs.items():
            print(f"  {name}: {path.name}")
        enriched = pd.read_csv(
            paths.read("comments_clustered"),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8",
        )
        summary = pd.read_csv(
            paths.read("clusters_summary"),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8",
        )
        posts_df, comments_df = load_scraper_data(input_dir)
        print("\n[graph] Reconstruyendo grafo con etiquetas de discurso...")
        run_graph(
            posts_df,
            comments_df,
            enriched,
            summary,
            paths,
            args.min_co_comments,
            export_metrics=args.export_metrics,
        )
        return 0

    if args.step in {"lang", "all"}:
        print("\n[0/4] Filtro de idioma...")
        if allowed_langs:
            print(f"  Idiomas permitidos: {', '.join(allowed_langs)}")
            print(
                f"  Umbral confianza={args.min_language_confidence}, "
                f"margen={args.min_language_margin}"
            )
        else:
            print("  Sin filtro (--languages all)")
        comments_for_analysis = run_lang_filter(
            comments_df,
            paths,
            languages=allowed_langs,
            min_language_confidence=args.min_language_confidence,
            min_language_margin=args.min_language_margin,
            keep_unknown_language=args.keep_unknown_language,
        )
        if args.step == "lang":
            print("\n=== Filtro de idioma completado ===")
            print(f"Siguiente: python analyze.py --step prep ... (usa {paths.comments_for_analysis.name})")
            return 0

    if args.step in {"prep", "all"}:
        comments_input = paths.read("comments_for_analysis")
        if args.step == "prep" and comments_input.exists():
            comments_for_analysis = pd.read_csv(
                comments_input,
                dtype=str,
                keep_default_na=False,
                encoding="utf-8",
            )
            print(f"  Usando {comments_input.name} ({len(comments_for_analysis)} filas)")
        print("\n[1/4] Preprocesado de comentarios...")
        enriched = run_prep(
            posts_df,
            comments_for_analysis,
            paths,
            args.min_comment_length,
            languages=allowed_langs,
            min_language_confidence=args.min_language_confidence,
            min_language_margin=args.min_language_margin,
            keep_unknown_language=args.keep_unknown_language,
        )
    elif paths.read("comments_enriched").exists():
        enriched = pd.read_csv(
            paths.read("comments_enriched"),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8",
        )

    clustered_input = paths.read("comments_clustered")
    summary_input = paths.read("clusters_summary")

    if args.step in {"cluster", "all"}:
        if enriched.empty:
            print("ERROR: no hay comentarios enriquecidos para clusterizar.", file=sys.stderr)
            return 1
        print("\n[2/4] Clustering de narrativas...")
        enriched, summary = run_cluster(enriched, paths, args.n_clusters)
    elif clustered_input.exists() and summary_input.exists():
        enriched = pd.read_csv(
            clustered_input,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8",
        )
        summary = pd.read_csv(
            summary_input,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8",
        )

    if args.step in {"graph", "all"}:
        if enriched.empty:
            print("ERROR: faltan comentarios enriquecidos para el grafo.", file=sys.stderr)
            return 1
        if summary.empty:
            summary = pd.DataFrame(columns=["cluster_id", "n_comments", "top_terms"])
        print("\n[3/4] Construcción del grafo...")
        run_graph(
            posts_df,
            comments_for_analysis,
            enriched,
            summary,
            paths,
            args.min_co_comments,
            export_metrics=args.export_metrics,
        )

    print("\n=== Análisis completado ===")
    print(f"Revisa {paths.clusters_summary.name} (clustering ciego).")
    print("Siguiente: python analyze.py --step discourse-init --output-dir ...")
    print(f"Abre {paths.graph_hashtags.name} y {paths.graph_users.name} en Gephi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
