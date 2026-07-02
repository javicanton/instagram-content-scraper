"""Construcción de grafos sociales, de hashtags y narrativos."""

from __future__ import annotations

from collections import Counter
from itertools import combinations
from pathlib import Path

import networkx as nx
import pandas as pd

from network import build_co_comment_edges, build_mention_edges


def _user_node(username: str) -> str:
    return f"user:{username}"


def _hashtag_node(tag: str) -> str:
    return f"hashtag:{tag.lstrip('#').lower()}"


def _profile_node(username: str) -> str:
    return f"profile:{username.lstrip('@').lower()}"


def _split_hashtags(value: str) -> list[str]:
    tags = []
    for part in str(value or "").split(";"):
        tag = part.strip().lstrip("#").lower()
        if tag:
            tags.append(tag)
    return sorted(set(tags))


def _add_bipartite_edges(
    edges: list[dict],
    left_prefix: str,
    left_id: str,
    right_prefix: str,
    right_id: str,
    edge_type: str,
    weight: float,
) -> None:
    edges.append(
        {
            "source": f"{left_prefix}:{left_id}",
            "target": f"{right_prefix}:{right_id}",
            "edge_type": edge_type,
            "weight": weight,
        }
    )


def build_hashtag_cooccurrence_edges(posts_df: pd.DataFrame) -> pd.DataFrame:
    """Aristas entre hashtags que aparecen juntos en el mismo post."""
    if posts_df.empty:
        return pd.DataFrame(columns=["source", "target", "edge_type", "weight"])

    pair_counts: Counter[tuple[str, str]] = Counter()

    for _, row in posts_df.iterrows():
        tags = _split_hashtags(str(row.get("hashtags", "")))
        for tag_a, tag_b in combinations(tags, 2):
            pair_counts[(tag_a, tag_b)] += 1

    rows = [
        {
            "source": _hashtag_node(a),
            "target": _hashtag_node(b),
            "edge_type": "hashtag_cooccurrence",
            "weight": weight,
        }
        for (a, b), weight in pair_counts.items()
    ]
    return pd.DataFrame(rows)


def build_user_hashtag_edges(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
) -> pd.DataFrame:
    """Aristas usuario/perfil → hashtag (uso en caption o comentario)."""
    weights: Counter[tuple[str, str, str]] = Counter()

    if not posts_df.empty:
        for _, row in posts_df.iterrows():
            profile = str(row.get("profile_username", "") or "").lstrip("@").lower()
            if not profile:
                continue
            for tag in _split_hashtags(str(row.get("hashtags", ""))):
                weights[(profile, tag, "profile_uses_hashtag")] += 1
            source_tag = str(row.get("source_hashtag", "") or "").strip().lower()
            if source_tag:
                weights[(profile, source_tag, "profile_from_hashtag_search")] += 1

    if not comments_df.empty:
        for _, row in comments_df.iterrows():
            author = str(row.get("author_username", "") or "").lstrip("@").lower()
            if not author:
                continue
            text = str(row.get("comment_text", "") or "")
            for tag in _split_hashtags(extract_hashtags_from_text(text)):
                weights[(author, tag, "user_uses_hashtag_comment")] += 1

    rows = []
    for (user, tag, edge_type), weight in weights.items():
        source = (
            _profile_node(user)
            if edge_type.startswith("profile")
            else _user_node(user)
        )
        rows.append(
            {
                "source": source,
                "target": _hashtag_node(tag),
                "edge_type": edge_type,
                "weight": weight,
            }
        )
    return pd.DataFrame(rows)


def extract_hashtags_from_text(text: str) -> str:
    import re

    tags = re.findall(r"#[\w\u00C0-\u024F\u1E00-\u1EFF]+", str(text), flags=re.UNICODE)
    return ";".join(tags)


def build_hashtag_nodes(posts_df: pd.DataFrame) -> pd.DataFrame:
    counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()

    if posts_df.empty:
        return pd.DataFrame(columns=["node_id", "node_type", "label", "post_count"])

    for _, row in posts_df.iterrows():
        for tag in _split_hashtags(str(row.get("hashtags", ""))):
            counts[tag] += 1
        source_tag = str(row.get("source_hashtag", "") or "").strip().lower()
        if source_tag:
            source_counts[source_tag] += 1

    nodes = []
    all_tags = set(counts) | set(source_counts)
    for tag in sorted(all_tags):
        nodes.append(
            {
                "node_id": _hashtag_node(tag),
                "node_type": "hashtag",
                "label": f"#{tag}",
                "post_count": int(counts.get(tag, 0)),
                "sourced_posts": int(source_counts.get(tag, 0)),
            }
        )
    return pd.DataFrame(nodes)


def build_user_network_nodes(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    enriched_df: pd.DataFrame,
) -> pd.DataFrame:
    nodes: dict[str, dict] = {}

    def add_node(node_id: str, node_type: str, label: str, **attrs) -> None:
        nodes[node_id] = {
            "node_id": node_id,
            "node_type": node_type,
            "label": label,
            **attrs,
        }

    if not posts_df.empty:
        for profile in posts_df["profile_username"].dropna().unique():
            profile = str(profile).lstrip("@")
            if profile:
                add_node(_profile_node(profile), "profile", profile)

    if not enriched_df.empty:
        for author, count in enriched_df["author_username"].value_counts().items():
            if author:
                add_node(
                    _user_node(author),
                    "user",
                    author,
                    comment_count=int(count),
                )
        if "discourse_stance" in enriched_df.columns:
            for author in enriched_df["author_username"].dropna().unique():
                author = str(author).lstrip("@")
                if not author:
                    continue
                subset = enriched_df[enriched_df["author_username"] == author]
                stance_counts = subset["discourse_stance"].value_counts().to_dict()
                key = _user_node(author)
                if key in nodes:
                    nodes[key]["discourse_stances"] = str(stance_counts)

    if not comments_df.empty and enriched_df.empty:
        for author in comments_df["author_username"].dropna().unique():
            author = str(author).lstrip("@")
            if author:
                add_node(_user_node(author), "user", author)

    return pd.DataFrame(nodes.values())


def build_narrative_edges(
    enriched_df: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> pd.DataFrame:
    edges: list[dict] = []

    if enriched_df.empty:
        return pd.DataFrame(columns=["source", "target", "edge_type", "weight"])

    for cluster_id, group in enriched_df.groupby("cluster_id"):
        summary_row = {}
        if not summary_df.empty:
            matches = summary_df[summary_df["cluster_id"].astype(str) == str(cluster_id)]
            if not matches.empty:
                summary_row = matches.iloc[0].to_dict()
        category_label = str(summary_row.get("discourse_category_label", "") or "").strip()
        narrative = category_label or f"narrativa_{cluster_id}"

        for author, count in Counter(group["author_username"].tolist()).items():
            if author:
                _add_bipartite_edges(
                    edges,
                    "user",
                    author,
                    "narrative",
                    narrative,
                    "user_narrative",
                    float(count),
                )

        for profile, count in Counter(group["profile_username"].tolist()).items():
            if profile:
                _add_bipartite_edges(
                    edges,
                    "profile",
                    profile,
                    "narrative",
                    narrative,
                    "profile_narrative",
                    float(count),
                )

    if not summary_df.empty and len(summary_df) > 1:
        term_sets = []
        for _, row in summary_df.iterrows():
            terms = {
                t.strip()
                for t in str(row.get("top_terms", "")).split(";")
                if t.strip()
            }
            term_sets.append((str(row["cluster_id"]), terms))

        for i, (cid_a, terms_a) in enumerate(term_sets):
            for cid_b, terms_b in term_sets[i + 1 :]:
                if not terms_a or not terms_b:
                    continue
                overlap = len(terms_a & terms_b)
                if overlap > 0:
                    sim = overlap / len(terms_a | terms_b)
                    edges.append(
                        {
                            "source": f"narrative:narrativa_{cid_a}",
                            "target": f"narrative:narrativa_{cid_b}",
                            "edge_type": "narrative_similarity",
                            "weight": round(sim, 4),
                        }
                    )

    return pd.DataFrame(edges)


def build_nodes(
    posts_df: pd.DataFrame,
    enriched_df: pd.DataFrame,
    summary_df: pd.DataFrame,
) -> pd.DataFrame:
    nodes: dict[str, dict] = {}

    def add_node(node_id: str, node_type: str, label: str, **attrs) -> None:
        nodes[node_id] = {
            "node_id": node_id,
            "node_type": node_type,
            "label": label,
            **attrs,
        }

    if not posts_df.empty:
        for _, row in posts_df.iterrows():
            profile = str(row.get("profile_username", "") or "").lstrip("@")
            if profile:
                add_node(f"profile:{profile}", "profile", profile)

    if not enriched_df.empty:
        for author, count in enriched_df["author_username"].value_counts().items():
            if author:
                add_node(
                    _user_node(author),
                    "user",
                    author,
                    comment_count=int(count),
                )

        for profile, count in enriched_df["profile_username"].value_counts().items():
            if profile:
                key = f"profile:{profile}"
                if key in nodes:
                    nodes[key]["comment_volume_on_posts"] = int(count)
                else:
                    add_node(
                        key,
                        "profile",
                        profile,
                        comment_volume_on_posts=int(count),
                    )

    if not summary_df.empty:
        for _, row in summary_df.iterrows():
            cid = str(row["cluster_id"])
            category_label = str(row.get("discourse_category_label", "") or "").strip()
            narrative = category_label or f"narrativa_{cid}"
            add_node(
                f"narrative:{narrative}",
                "narrative",
                narrative,
                cluster_id=cid,
                discourse_category_id=str(row.get("discourse_category_id", "")),
                discourse_category_label=category_label,
                n_comments=int(row.get("n_comments", 0)),
                top_terms=str(row.get("top_terms", ""))[:500],
            )

    hashtag_nodes = build_hashtag_nodes(posts_df)
    for _, row in hashtag_nodes.iterrows():
        nodes[row["node_id"]] = row.to_dict()

    return pd.DataFrame(nodes.values())


def export_graphml(nodes_df: pd.DataFrame, edges_df: pd.DataFrame, output_path: Path) -> None:
    graph = nx.Graph()

    for _, row in nodes_df.iterrows():
        node_id = row["node_id"]
        attrs = row.drop(labels=["node_id"]).to_dict()
        graph.add_node(node_id, **{k: str(v) for k, v in attrs.items()})

    for _, row in edges_df.iterrows():
        graph.add_edge(
            row["source"],
            row["target"],
            edge_type=row["edge_type"],
            weight=float(row["weight"]),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(graph, output_path)


def _normalize_social_edges(social_edges: pd.DataFrame) -> pd.DataFrame:
    if social_edges.empty:
        return social_edges

    out = social_edges.copy()
    out["source"] = out["source"].map(_user_node)
    out["target"] = out["target"].map(_user_node)
    return out


def build_full_graph(
    posts_df: pd.DataFrame,
    comments_df: pd.DataFrame,
    enriched_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    *,
    min_co_comments: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    social_parts = [
        build_mention_edges(posts_df, comments_df),
        build_co_comment_edges(comments_df, min_shared_posts=min_co_comments),
    ]
    social_edges = pd.concat(
        [df for df in social_parts if not df.empty],
        ignore_index=True,
    )
    if social_edges.empty:
        social_edges = pd.DataFrame(
            columns=["source", "target", "edge_type", "weight"]
        )
    else:
        social_edges = _normalize_social_edges(social_edges)

    hashtag_cooc = build_hashtag_cooccurrence_edges(posts_df)
    user_hashtag = build_user_hashtag_edges(posts_df, comments_df)

    narrative_edges = build_narrative_edges(enriched_df, summary_df)
    all_edges = pd.concat(
        [social_edges, hashtag_cooc, user_hashtag, narrative_edges],
        ignore_index=True,
    )
    nodes = build_nodes(posts_df, enriched_df, summary_df)
    user_network_edges = pd.concat(
        [social_edges, user_hashtag],
        ignore_index=True,
    )
    hashtag_edges = pd.concat(
        [hashtag_cooc, user_hashtag],
        ignore_index=True,
    )
    return nodes, all_edges, social_edges, hashtag_edges, user_network_edges
