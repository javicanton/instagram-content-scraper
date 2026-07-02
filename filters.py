"""Filtros de publicaciones por engagement (likes, vistas, comentarios)."""

from __future__ import annotations

import pandas as pd

SORTABLE_METRICS = ("likes", "views", "comments")

METRIC_COLUMNS = {
    "likes": "like_count",
    "views": "view_count",
    "comments": "comment_count",
}


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def _profile_threshold(
    values: pd.Series,
    metric: str,
    factor: float,
) -> float | None:
    numeric = _to_numeric(values)

    if metric == "views":
        numeric = numeric[numeric > 0]
        if numeric.empty:
            return None
    elif numeric.empty:
        return None

    mean = float(numeric.mean())
    return mean * factor


def filter_above_profile_avg(
    posts_df: pd.DataFrame,
    metrics: list[str],
    *,
    factor: float = 1.0,
    profile_col: str = "profile_username",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Conserva posts que superan la media de su perfil en cada métrica indicada.

    La media se calcula por profile_username. Para vistas, solo entran posts
    con view_count > 0 al calcular el promedio (vídeos/reels).

    Comparación: valor > umbral (estrictamente por encima de media × factor).
    """
    if posts_df.empty or not metrics:
        return posts_df, pd.DataFrame()

    unknown = set(metrics) - set(METRIC_COLUMNS)
    if unknown:
        raise ValueError(f"Métricas desconocidas: {', '.join(sorted(unknown))}")

    out = posts_df.copy()
    if profile_col not in out.columns:
        out[profile_col] = ""

    keep_mask = pd.Series(True, index=out.index)
    stats_rows: list[dict] = []

    for profile, group in out.groupby(out[profile_col].astype(str), dropna=False):
        profile_key = profile or "(sin perfil)"
        group_idx = group.index

        for metric in metrics:
            col = METRIC_COLUMNS[metric]
            values = _to_numeric(group[col])
            threshold = _profile_threshold(values, metric, factor)

            stats_rows.append(
                {
                    "profile_username": profile_key,
                    "metric": metric,
                    "profile_mean": round(
                        float(values[values > 0].mean()) if metric == "views" and (values > 0).any()
                        else float(values.mean()) if len(values) else 0,
                        2,
                    ),
                    "threshold": round(threshold, 2) if threshold is not None else "",
                    "posts_in_profile": len(group),
                }
            )

            if threshold is None:
                keep_mask.loc[group_idx] = False
                continue

            if metric == "views":
                metric_ok = (values > threshold) & (values > 0)
            else:
                metric_ok = values > threshold

            keep_mask.loc[group_idx] = keep_mask.loc[group_idx] & metric_ok

    filtered = out[keep_mask].reset_index(drop=True)
    stats = pd.DataFrame(stats_rows)
    return filtered, stats


def filter_posts(
    posts_df: pd.DataFrame,
    *,
    min_likes: int | None = None,
    min_views: int | None = None,
    min_comments: int | None = None,
    above_profile_avg: list[str] | None = None,
    above_profile_avg_factor: float = 1.0,
    top_by: str | None = None,
    max_posts: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filtra y/o ordena posts por métricas de engagement."""
    stats = pd.DataFrame()
    if posts_df.empty:
        return posts_df, stats

    out = posts_df.copy()
    likes = _to_numeric(out.get("like_count", pd.Series(0, index=out.index)))
    views = _to_numeric(out.get("view_count", pd.Series(0, index=out.index)))
    comments = _to_numeric(out.get("comment_count", pd.Series(0, index=out.index)))

    if min_likes is not None and min_likes > 0:
        out = out[likes.loc[out.index] >= min_likes]

    if min_views is not None and min_views > 0:
        out = out[views.loc[out.index] >= min_views]

    if min_comments is not None and min_comments > 0:
        out = out[comments.loc[out.index] >= min_comments]

    if above_profile_avg:
        out, avg_stats = filter_above_profile_avg(
            out,
            above_profile_avg,
            factor=above_profile_avg_factor,
        )
        stats = avg_stats

    metric_col = METRIC_COLUMNS.get(top_by or "")

    if metric_col and metric_col in out.columns:
        out = out.assign(_sort=_to_numeric(out[metric_col]))
        out = out.sort_values("_sort", ascending=False).drop(columns="_sort")

    if max_posts is not None and max_posts > 0 and len(out) > max_posts:
        out = out.head(max_posts)

    return out.reset_index(drop=True), stats


def describe_filter(
    before: int,
    after: int,
    *,
    min_likes: int | None,
    min_views: int | None,
    min_comments: int | None,
    above_profile_avg: list[str] | None,
    above_profile_avg_factor: float | None,
    top_by: str | None,
) -> str:
    parts = []
    if min_likes:
        parts.append(f"likes≥{min_likes}")
    if min_views:
        parts.append(f"vistas≥{min_views}")
    if min_comments:
        parts.append(f"comentarios≥{min_comments}")
    if above_profile_avg:
        metrics = "+".join(above_profile_avg)
        factor = above_profile_avg_factor or 1.0
        parts.append(f">{factor}×media/perfil ({metrics})")
    if top_by:
        parts.append(f"ordenado por {top_by}")
    filt = ", ".join(parts) if parts else "sin filtros"
    return f"  Filtro engagement ({filt}): {before} → {after} posts"
