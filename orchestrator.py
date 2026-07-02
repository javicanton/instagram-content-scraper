#!/usr/bin/env python3
"""CLI principal para scrapear Instagram vía instatouch y exportar CSV unificados."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

from config import (
    DUAL_CORPUS_FILES,
    DEFAULT_HASHTAGS_FILE,
    EXAMPLE_HASHTAGS_FILE,
    load_settings,
)
from corpora_config import CorpusConfig, load_corpora_config
from filters import METRIC_COLUMNS, describe_filter, filter_posts
from instatouch_runner import InstatouchRunner
from merger import drop_comments_for_posts, merge_comments, merge_posts, save_csv
from normalizer import (
    normalize_comments,
    normalize_posts,
    resolve_post_ref,
)
from recovery import (
    comments_look_empty,
    hashtag_status,
    import_hashtag_posts_from_raw,
    load_existing_output,
    posts_needing_comments,
    repair_post_urls,
    parse_comment_count,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scraper de contenido de Instagram → CSV tabulares (instatouch + Python)."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["hashtag", "hashtags", "dual", "multi"],
        help="Modo: hashtag (uno), hashtags (CSV), dual/multi (varios corpus).",
    )
    parser.add_argument(
        "--query",
        default="",
        help="Hashtag sin # en modo hashtag.",
    )
    parser.add_argument(
        "--file",
        default="",
        help="Alias de --hashtag-file.",
    )
    parser.add_argument(
        "--hashtag-file",
        default="",
        help="CSV de hashtags para modo hashtags (default: hashtags.csv o hashtags.example.csv).",
    )
    parser.add_argument("--max-posts", type=int, default=40, help="Máximo de posts a scrapear.")
    parser.add_argument(
        "--max-posts-per-hashtag",
        type=int,
        default=None,
        help="Máximo de posts por hashtag en modo hashtags (default: --max-posts).",
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=200,
        help="Máximo de comentarios por post con --with-comments.",
    )
    parser.add_argument(
        "--max-comments-per-post",
        type=int,
        default=None,
        help="Alias de --max-comments para compatibilidad.",
    )
    parser.add_argument(
        "--with-comments",
        action="store_true",
        help="Descargar comentarios de cada post obtenido.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/output",
        help="Directorio de CSV finales (posts.csv, comments.csv).",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="No solicitar confirmación interactiva.",
    )
    parser.add_argument(
        "--min-likes",
        type=int,
        default=None,
        help="Conservar solo posts con al menos N likes.",
    )
    parser.add_argument(
        "--min-views",
        type=int,
        default=None,
        help="Conservar solo posts con al menos N visualizaciones (vídeos/reels).",
    )
    parser.add_argument(
        "--min-comments-count",
        type=int,
        default=None,
        help="Conservar solo posts con al menos N comentarios (conteo del post, no scrapeados).",
    )
    parser.add_argument(
        "--top-by",
        choices=["likes", "views", "comments"],
        default=None,
        help="Ordenar posts por métrica antes de aplicar --keep-top.",
    )
    parser.add_argument(
        "--keep-top",
        type=int,
        default=None,
        help="Tras filtrar, conservar solo los N posts con mayor métrica (--top-by).",
    )
    parser.add_argument(
        "--above-profile-avg",
        default="",
        help="Métricas por las que filtrar respecto a la media del perfil: likes,views,comments (separadas por coma).",
    )
    parser.add_argument(
        "--above-profile-avg-factor",
        type=float,
        default=1.0,
        help="Multiplicador de la media del perfil (1.0 = superar la media; 1.2 = 20%% por encima).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Omitir hashtags ya completos en posts.csv; reanudar comentarios a medias.",
    )
    parser.add_argument(
        "--import-raw",
        action="store_true",
        help="Antes de scrapear, importar posts desde data/raw para hashtags sin filas en posts.csv.",
    )
    parser.add_argument(
        "--force-comments",
        action="store_true",
        help="Re-scrapear comentarios aunque el post ya figure en comments.csv.",
    )
    parser.add_argument(
        "--repair-posts",
        action="store_true",
        help="Corregir post_url en posts.csv usando shortcodes de data/raw.",
    )
    parser.add_argument(
        "--corpus-id",
        default="",
        help="Valor de corpus_id al guardar (p. ej. violencia). Modo hashtags con --output-dir.",
    )
    parser.add_argument(
        "--corpora-config",
        default="",
        help="YAML con varios corpus (default: corpora.yaml o corpora.example.yaml). Modos dual/multi.",
    )
    parser.add_argument(
        "--only-corpus",
        default="",
        help="En modo dual/multi: procesar solo este corpus_id.",
    )
    return parser.parse_args()


def resolve_hashtags_path(args: argparse.Namespace) -> Path:
    """Resuelve el CSV de hashtags: --hashtag-file > --file > hashtags.csv > ejemplo."""
    if args.hashtag_file:
        return Path(args.hashtag_file)
    if args.file:
        return Path(args.file)
    if DEFAULT_HASHTAGS_FILE.exists():
        return DEFAULT_HASHTAGS_FILE
    return EXAMPLE_HASHTAGS_FILE


def attach_corpus_id(df: pd.DataFrame, corpus_id: str) -> pd.DataFrame:
    """Añade corpus_id a posts o comentarios."""
    if df.empty:
        return df
    out = df.copy()
    out["corpus_id"] = corpus_id
    return out


def persist_outputs(
    output_dir: Path,
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    *,
    replace_comment_post_ids: set[str] | None = None,
) -> tuple[int, int, int, int]:
    """Merge incremental y guardado de posts.csv y comments.csv."""
    output_dir.mkdir(parents=True, exist_ok=True)
    posts_path = output_dir / "posts.csv"
    comments_path = output_dir / "comments.csv"

    if replace_comment_post_ids:
        existing_comments = (
            pd.read_csv(comments_path, dtype=str, keep_default_na=False, encoding="utf-8")
            if comments_path.exists()
            else pd.DataFrame()
        )
        trimmed = drop_comments_for_posts(existing_comments, replace_comment_post_ids)
        if len(trimmed) != len(existing_comments):
            save_csv(comments_path, trimmed)

    merged_posts, new_posts = merge_posts(posts_path, posts_df)
    merged_comments, new_comments = merge_comments(comments_path, comments_df)

    save_csv(posts_path, merged_posts)
    save_csv(comments_path, merged_comments)
    return len(merged_posts), new_posts, len(merged_comments), new_comments


def run_multi_corpus_mode(
    runner: InstatouchRunner,
    args: argparse.Namespace,
    settings,
    base_output_dir: Path,
) -> int:
    """Ejecuta varios corpus definidos en corpora.yaml (o dual legacy)."""
    exit_code = 0
    config_path = Path(args.corpora_config) if args.corpora_config else None

    try:
        corpora = load_corpora_config(config_path)
    except FileNotFoundError:
        corpora = [
            CorpusConfig(id=cid, hashtags_file=path)
            for cid, path in DUAL_CORPUS_FILES
        ]

    if args.only_corpus:
        corpora = [c for c in corpora if c.id == args.only_corpus]
        if not corpora:
            print(f"ERROR: corpus '{args.only_corpus}' no encontrado en la configuración.", file=sys.stderr)
            return 1

    for corpus in corpora:
        corpus_id = corpus.id
        hashtags_path = Path(corpus.hashtags_file)
        if not hashtags_path.exists():
            print(
                f"ERROR: archivo de hashtags no encontrado: {hashtags_path}",
                file=sys.stderr,
            )
            return 1

        output_dir = base_output_dir / corpus_id
        print(f"\n{'=' * 60}")
        print(f"Corpus: {corpus_id} ← {hashtags_path.name}")
        if getattr(corpus, "description", ""):
            print(f"  {corpus.description}")
        print(f"Salida: {output_dir}")
        print(f"{'=' * 60}")

        run_args = argparse.Namespace(**{**vars(args), "corpus_id": corpus_id})
        posts_df, comments_df = run_hashtags_list_mode(
            runner,
            hashtags_path,
            run_args,
            settings,
            output_dir=output_dir,
            corpus_id=corpus_id,
        )

        if posts_df.empty and comments_df.empty:
            print(f"AVISO: corpus {corpus_id} sin datos nuevos.")
            exit_code = 2

        time.sleep(settings.delay_between_posts_sec)

    return exit_code


def run_dual_mode(
    runner: InstatouchRunner,
    args: argparse.Namespace,
    settings,
    base_output_dir: Path,
) -> int:
    """Alias de run_multi_corpus_mode (compatibilidad)."""
    return run_multi_corpus_mode(runner, args, settings, base_output_dir)


def load_hashtags_csv(path: Path) -> list[str]:
    """Un hashtag por línea, o CSV con columna `hashtag`."""
    if not path.exists():
        return []

    raw_lines = [
        ln.strip().lstrip("\ufeff")
        for ln in path.read_text(encoding="utf-8-sig").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not raw_lines:
        return []

    header = raw_lines[0].lower()
    if header in {"hashtag", "tag", "tags"}:
        raw_lines = raw_lines[1:]

    if len(raw_lines) == 1 and "," in raw_lines[0] and header not in {"hashtag", "tag", "tags"}:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
        col = "hashtag" if "hashtag" in df.columns else df.columns[0]
        return [str(v).strip().lstrip("#") for v in df[col].tolist() if str(v).strip()]

    tags: list[str] = []
    for line in raw_lines:
        tag = line.split(",")[0].strip().lstrip("#")
        if tag and tag.lower() not in {"hashtag", "tag", "tags"}:
            tags.append(tag)
    return tags


def parse_above_profile_avg(raw: str) -> list[str]:
    valid = set(METRIC_COLUMNS)
    metrics = [m.strip() for m in raw.split(",") if m.strip()]
    unknown = set(metrics) - valid
    if unknown:
        raise ValueError(
            f"Métricas desconocidas en --above-profile-avg: {', '.join(sorted(unknown))}"
        )
    return metrics


def apply_engagement_filters(
    posts_df: pd.DataFrame,
    args: argparse.Namespace,
    *,
    profile_label: str = "",
) -> pd.DataFrame:
    """Filtra posts por likes/vistas/comentarios; solo afecta comentarios scrapeados."""
    if posts_df.empty:
        return posts_df

    above_avg = parse_above_profile_avg(args.above_profile_avg) if args.above_profile_avg else []

    has_filter = any(
        [
            args.min_likes,
            args.min_views,
            args.min_comments_count,
            above_avg,
            args.top_by,
            args.keep_top,
        ]
    )
    if not has_filter:
        return posts_df

    before = len(posts_df)
    filtered, avg_stats = filter_posts(
        posts_df,
        min_likes=args.min_likes,
        min_views=args.min_views,
        min_comments=args.min_comments_count,
        above_profile_avg=above_avg or None,
        above_profile_avg_factor=args.above_profile_avg_factor,
        top_by=args.top_by,
        max_posts=args.keep_top,
    )
    prefix = f"@{profile_label} " if profile_label else ""
    print(
        describe_filter(
            before,
            len(filtered),
            min_likes=args.min_likes,
            min_views=args.min_views,
            min_comments=args.min_comments_count,
            above_profile_avg=above_avg or None,
            above_profile_avg_factor=args.above_profile_avg_factor,
            top_by=args.top_by,
        ).replace("  Filtro", f"  {prefix}Filtro", 1)
    )
    if not avg_stats.empty:
        for _, row in avg_stats.iterrows():
            print(
                f"    media {row['profile_username']} ({row['metric']}): "
                f"{row['profile_mean']} → umbral {row['threshold']}"
            )
    if before > 0 and filtered.empty:
        print(
            "  AVISO: ningún post pasó el filtro. "
            "Sube --max-posts para scrapear más candidatos o baja los umbrales."
        )
    return filtered


def scrape_comments_for_posts(
    runner: InstatouchRunner,
    posts_df: pd.DataFrame,
    settings,
    max_comments: int,
    *,
    existing_comments: pd.DataFrame | None = None,
    force: bool = False,
) -> pd.DataFrame:
    if posts_df.empty:
        return pd.DataFrame()

    scraped_ids: set[str] = set()
    if not force and existing_comments is not None and not existing_comments.empty:
        if comments_look_empty(existing_comments):
            scraped_ids = set()
        elif "comment_text" in existing_comments.columns:
            text_by_post = (
                existing_comments.groupby("post_id")["comment_text"]
                .apply(lambda s: s.fillna("").astype(str).str.strip().ne("").any())
            )
            scraped_ids = set(text_by_post[text_by_post].index.astype(str))
        else:
            scraped_ids = set(existing_comments["post_id"].astype(str))

    all_comments: list[pd.DataFrame] = []
    pending = posts_df[
        ~posts_df["post_id"].astype(str).isin(scraped_ids)
    ].reset_index(drop=True)
    total = len(pending)
    skipped = len(posts_df) - total
    if skipped:
        print(f"  Omitiendo {skipped} posts que ya tienen comentarios en CSV")

    for idx, row in pending.iterrows():
        post_ref = resolve_post_ref(row)
        post_id = str(row.get("post_id", ""))
        if not post_ref:
            print(f"  Comentarios [{idx + 1}/{total}] post_id={post_id}... omitido (sin URL/id)")
            continue

        reported_comments = parse_comment_count(row.get("comment_count"))
        if reported_comments == 0:
            print(
                f"  Comentarios [{idx + 1}/{total}] post_id={post_id}..."
                " omitido (comment_count=0 en metadata del post)"
            )
            continue

        print(f"  Comentarios [{idx + 1}/{total}] post_id={post_id}...")
        result = runner.scrape_comments(str(post_ref), max_comments, media_id=post_id)

        if not result.success:
            print(f"    ERROR: no se pudieron obtener comentarios para {post_id}")
            if result.stderr:
                print(f"    {result.stderr.strip()[:300]}")
        else:
            comments_df = normalize_comments(
                result.csv_path,
                json_path=result.json_path,
                post_id=post_id,
            )
            if max_comments and max_comments > 0 and len(comments_df) > max_comments:
                comments_df = comments_df.head(max_comments)
            with_text = int(
                comments_df.get("comment_text", pd.Series(dtype=str))
                .fillna("")
                .astype(str)
                .str.strip()
                .ne("")
                .sum()
            )
            print(f"    → {len(comments_df)} comentarios normalizados ({with_text} con texto)")
            if not comments_df.empty:
                all_comments.append(comments_df)

        time.sleep(settings.delay_between_comment_jobs_sec)

    if not all_comments:
        return pd.DataFrame()
    return pd.concat(all_comments, ignore_index=True)


def run_hashtag_mode(
    runner: InstatouchRunner,
    tag: str,
    args: argparse.Namespace,
    settings,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    tag = tag.lstrip("#")
    print(f"Scrapeando hashtag #{tag} (max {args.max_posts} posts)...")
    result = runner.scrape_hashtag(tag, args.max_posts)

    if not result.success:
        print(f"ERROR al scrapear hashtag #{tag}")
        return pd.DataFrame(), pd.DataFrame()

    print(f"  Raw CSV: {result.csv_path}")
    posts_df = normalize_posts(
        result.csv_path,
        json_path=result.json_path,
        source_mode="hashtag",
        default_source_hashtag=tag,
    )
    print(f"  → {len(posts_df)} posts normalizados")
    posts_df = apply_engagement_filters(posts_df, args)
    if args.max_posts and len(posts_df) > args.max_posts:
        posts_df = posts_df.head(args.max_posts).reset_index(drop=True)
        print(f"  → {len(posts_df)} posts tras tope --max-posts")

    comments_df = pd.DataFrame()
    if args.with_comments and not posts_df.empty:
        print("Descargando comentarios por post...")
        comments_df = scrape_comments_for_posts(
            runner, posts_df, settings, args.max_comments
        )

    return posts_df, comments_df


def _maybe_import_raw_for_tag(
    tag: str,
    existing_posts: pd.DataFrame,
    raw_dir: Path,
    args: argparse.Namespace,
    corpus_id: str,
) -> pd.DataFrame:
    """Importa posts desde raw si --import-raw y el hashtag no está en CSV."""
    if not args.import_raw:
        return pd.DataFrame()
    if hashtag_status(existing_posts, pd.DataFrame(), tag, with_comments=False) != "pending":
        return pd.DataFrame()

    per_tag = args.max_posts_per_hashtag or args.max_posts
    imported = import_hashtag_posts_from_raw(
        tag,
        raw_dir,
        corpus_id=corpus_id or args.corpus_id,
        max_posts=per_tag,
    )
    if not imported.empty:
        print(f"  Importados {len(imported)} posts desde data/raw para #{tag}")
    return imported


def run_hashtags_list_mode(
    runner: InstatouchRunner,
    hashtags_path: Path,
    args: argparse.Namespace,
    settings,
    *,
    output_dir: Path | None = None,
    corpus_id: str = "",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Recorre hashtags; guarda en CSV tras cada hashtag si output_dir está definido."""
    tags = load_hashtags_csv(hashtags_path)
    if not tags:
        print(f"No se encontraron hashtags en {hashtags_path}")
        return pd.DataFrame(), pd.DataFrame()

    per_tag = args.max_posts_per_hashtag or args.max_posts
    corpus_id = corpus_id or args.corpus_id
    raw_dir = settings.raw_dir
    save_each = output_dir is not None

    existing_posts, existing_comments = (
        load_existing_output(output_dir)
        if save_each
        and (args.resume or args.import_raw or args.repair_posts or args.force_comments)
        else (pd.DataFrame(), pd.DataFrame())
    )

    if save_each and args.repair_posts and not existing_posts.empty:
        repaired = repair_post_urls(existing_posts, raw_dir)
        changed = int((repaired["post_url"] != existing_posts["post_url"]).sum())
        if changed:
            save_csv(output_dir / "posts.csv", repaired)
            existing_posts = repaired
            print(f"  Reparadas {changed} URLs de post en {output_dir / 'posts.csv'}")

    if save_each and args.force_comments and comments_look_empty(existing_comments):
        print(
            "  comments.csv sin texto: usa --with-comments para volver a descargar "
            "(se reemplazarán filas de los posts re-scrapeados)"
        )

    if save_each and args.import_raw:
        to_import: list[pd.DataFrame] = []
        for tag in tags:
            if hashtag_status(existing_posts, existing_comments, tag, with_comments=False) != "pending":
                continue
            imported = import_hashtag_posts_from_raw(
                tag, raw_dir, corpus_id=corpus_id, max_posts=per_tag
            )
            if not imported.empty:
                to_import.append(imported)
        if to_import:
            bulk = pd.concat(to_import, ignore_index=True)
            if corpus_id:
                bulk = attach_corpus_id(bulk, corpus_id)
            persist_outputs(output_dir, bulk, pd.DataFrame())
            existing_posts, existing_comments = load_existing_output(output_dir)
            print(f"  Importados {len(bulk)} posts desde data/raw → {output_dir / 'posts.csv'}")

    session_posts: list[pd.DataFrame] = []
    session_comments: list[pd.DataFrame] = []

    for i, tag in enumerate(tags, start=1):
        print(f"\n--- Hashtag [{i}/{len(tags)}] #{tag} ---")
        posts_new = pd.DataFrame()
        comments_new = pd.DataFrame()

        if save_each and args.resume:
            status = hashtag_status(
                existing_posts,
                existing_comments,
                tag,
                with_comments=args.with_comments,
            )
            if status == "complete":
                print(f"  Omitido (ya completo en {output_dir / 'posts.csv'})")
                continue
            if status == "needs_comments":
                pending = posts_needing_comments(existing_posts, existing_comments, tag)
                print(f"  Reanudando comentarios: {len(pending)} posts pendientes")
                comments_new = scrape_comments_for_posts(
                    runner,
                    pending,
                    settings,
                    args.max_comments,
                    existing_comments=existing_comments,
                    force=args.force_comments,
                )

        if posts_new.empty and comments_new.empty:
            if (
                save_each
                and args.resume
                and hashtag_status(
                    existing_posts, existing_comments, tag, with_comments=False
                )
                != "pending"
            ):
                pass  # solo comentarios, posts ya en CSV
            else:
                imported = _maybe_import_raw_for_tag(
                    tag, existing_posts, raw_dir, args, corpus_id
                )
                if not imported.empty:
                    posts_new = imported
                else:
                    posts_new, comments_new = run_hashtag_mode(
                        runner,
                        tag,
                        argparse.Namespace(**{**vars(args), "max_posts": per_tag}),
                        settings,
                    )

        if not posts_new.empty:
            posts_new = posts_new.copy()
            posts_new["source_mode"] = "hashtags"
            if corpus_id:
                posts_new = attach_corpus_id(posts_new, corpus_id)

        if args.with_comments and not posts_new.empty and comments_new.empty:
            combined_posts = (
                pd.concat([existing_posts, posts_new], ignore_index=True)
                if not existing_posts.empty
                else posts_new
            )
            pending = posts_needing_comments(combined_posts, existing_comments, tag)
            if not pending.empty:
                print(f"  Descargando comentarios ({len(pending)} posts)...")
                comments_new = scrape_comments_for_posts(
                    runner,
                    pending,
                    settings,
                    args.max_comments,
                    existing_comments=existing_comments,
                    force=args.force_comments,
                )

        if corpus_id and not comments_new.empty:
            comments_new = attach_corpus_id(comments_new, corpus_id)

        if not posts_new.empty:
            session_posts.append(posts_new)
        if not comments_new.empty:
            session_comments.append(comments_new)

        if save_each and (not posts_new.empty or not comments_new.empty):
            replace_ids: set[str] | None = None
            if args.force_comments and not comments_new.empty:
                replace_ids = set(comments_new["post_id"].astype(str))
            persist_outputs(
                output_dir,
                posts_new,
                comments_new,
                replace_comment_post_ids=replace_ids,
            )
            existing_posts, existing_comments = load_existing_output(output_dir)
            total_p = len(existing_posts)
            total_c = len(existing_comments)
            print(f"  Guardado incremental → {total_p} posts, {total_c} comentarios en {output_dir}")

        time.sleep(settings.delay_between_posts_sec)

    posts_out = pd.concat(session_posts, ignore_index=True) if session_posts else pd.DataFrame()
    comments_out = (
        pd.concat(session_comments, ignore_index=True) if session_comments else pd.DataFrame()
    )
    return posts_out, comments_out


def main() -> int:
    args = parse_args()
    max_comments = args.max_comments_per_post or args.max_comments
    args.max_comments = max_comments

    if args.above_profile_avg:
        try:
            parse_above_profile_avg(args.above_profile_avg)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    output_dir = Path(args.output_dir)
    raw_dir = Path("data/raw")

    try:
        settings = load_settings(output_dir=output_dir, raw_dir=raw_dir)
    except ValueError as exc:
        print(f"Configuración: {exc}", file=sys.stderr)
        return 1

    runner = InstatouchRunner(settings)
    posts_path = output_dir / "posts.csv"
    comments_path = output_dir / "comments.csv"

    if args.mode == "hashtag":
        if not args.query:
            print("ERROR: --query <hashtag> es obligatorio en modo hashtag", file=sys.stderr)
            return 1
        posts_df, comments_df = run_hashtag_mode(runner, args.query, args, settings)

    elif args.mode == "hashtags":
        hashtags_path = resolve_hashtags_path(args)
        if not hashtags_path.exists():
            print(
                f"ERROR: archivo de hashtags no encontrado: {hashtags_path}\n"
                f"Copia hashtags.example.csv → hashtags.csv y añade tus hashtags (uno por línea).",
                file=sys.stderr,
            )
            return 1
        print(f"Hashtags desde: {hashtags_path}")
        posts_df, comments_df = run_hashtags_list_mode(
            runner,
            hashtags_path,
            args,
            settings,
            output_dir=output_dir,
            corpus_id=args.corpus_id,
        )
        ep, ec = load_existing_output(output_dir)
        print("\n=== Resumen ===")
        print(f"Posts totales:     {len(ep)} → {posts_path}")
        print(f"Comentarios total: {len(ec)} → {comments_path}")
        return 0 if (len(ep) or len(ec)) else 2

    elif args.mode in {"dual", "multi"}:
        return run_multi_corpus_mode(runner, args, settings, output_dir)

    else:
        print(f"Modo desconocido: {args.mode}", file=sys.stderr)
        return 1

    merged_posts, new_posts = merge_posts(posts_path, posts_df)
    merged_comments, new_comments = merge_comments(comments_path, comments_df)

    save_csv(posts_path, merged_posts)
    save_csv(comments_path, merged_comments)

    print("\n=== Resumen ===")
    print(f"Posts nuevos:      {new_posts}")
    print(f"Posts totales:     {len(merged_posts)} → {posts_path}")
    print(f"Comentarios nuevos:{new_comments}")
    print(f"Comentarios total: {len(merged_comments)} → {comments_path}")

    if posts_df.empty and comments_df.empty:
        print("\nAVISO: no se obtuvieron datos. Revisa sesión, rate limits o el objetivo.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
