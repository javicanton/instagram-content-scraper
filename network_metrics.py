"""Cálculo de métricas de red con networkx para exportación analítica."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd


METRIC_COLUMNS = [
    "graph_type",
    "node",
    "degree",
    "in_degree",
    "out_degree",
    "betweenness",
    "eigenvector",
    "community",
]


def _nan() -> float:
    return float("nan")


def _community_partition(graph: nx.Graph) -> dict[Any, int]:
    """Asigna comunidad con Louvain o greedy modularity como fallback."""
    try:
        import community as community_louvain  # python-louvain

        undirected = graph.to_undirected() if graph.is_directed() else graph
        return community_louvain.best_partition(undirected)
    except Exception:  # noqa: BLE001
        pass

    undirected = graph.to_undirected() if graph.is_directed() else graph
    if undirected.number_of_nodes() == 0:
        return {}

    communities = nx.community.greedy_modularity_communities(undirected)
    partition: dict[Any, int] = {}
    for idx, comm in enumerate(communities):
        for node in comm:
            partition[node] = idx
    return partition


def _eigenvector_centrality(graph: nx.Graph) -> dict[Any, float]:
    """Eigenvector centrality; NaN si el grafo no converge."""
    if graph.number_of_nodes() == 0:
        return {}
    try:
        return nx.eigenvector_centrality(graph, max_iter=500)
    except (nx.PowerIterationFailedConvergence, nx.NetworkXError):
        return {node: _nan() for node in graph.nodes()}


def _betweenness(graph: nx.Graph) -> dict[Any, float]:
    if graph.number_of_nodes() == 0:
        return {}
    return nx.betweenness_centrality(graph)


def _metrics_for_graph(
    graph: nx.Graph,
    graph_type: str,
    *,
    directed: bool = False,
    compute_eigenvector: bool = False,
) -> list[dict[str, Any]]:
    """Calcula métricas por nodo para un grafo networkx."""
    if graph.number_of_nodes() == 0:
        return []

    communities = _community_partition(graph)
    betweenness = _betweenness(graph)
    eigenvector = _eigenvector_centrality(graph) if compute_eigenvector else {}

    rows: list[dict[str, Any]] = []
    for node in graph.nodes():
        if directed and graph.is_directed():
            degree_val = graph.degree(node)
            in_deg = graph.in_degree(node)
            out_deg = graph.out_degree(node)
        else:
            undirected = graph.to_undirected() if graph.is_directed() else graph
            degree_val = undirected.degree(node)
            in_deg = _nan()
            out_deg = _nan()

        rows.append(
            {
                "graph_type": graph_type,
                "node": str(node),
                "degree": float(degree_val),
                "in_degree": float(in_deg) if not (isinstance(in_deg, float) and math.isnan(in_deg)) else in_deg,
                "out_degree": float(out_deg) if not (isinstance(out_deg, float) and math.isnan(out_deg)) else out_deg,
                "betweenness": betweenness.get(node, _nan()),
                "eigenvector": eigenvector.get(node, _nan()) if compute_eigenvector else _nan(),
                "community": communities.get(node, _nan()),
            }
        )
    return rows


def build_hashtag_metric_graph(
    hashtag_nodes: pd.DataFrame,
    hashtag_edges: pd.DataFrame,
) -> nx.Graph:
    """Grafo no dirigido de co-ocurrencia de hashtags."""
    graph = nx.Graph()
    if not hashtag_nodes.empty:
        for _, row in hashtag_nodes.iterrows():
            graph.add_node(row["node_id"])
    if not hashtag_edges.empty:
        cooc = hashtag_edges[hashtag_edges["edge_type"] == "hashtag_cooccurrence"]
        for _, row in cooc.iterrows():
            graph.add_edge(row["source"], row["target"], weight=float(row.get("weight", 1)))
    return graph


def build_user_metric_graph(user_edges: pd.DataFrame) -> nx.DiGraph | nx.Graph:
    """Grafo de usuarios: dirigido si hay menciones, no dirigido si solo co-comentario."""
    has_mentions = (
        not user_edges.empty
        and user_edges["edge_type"].str.contains("mention", na=False).any()
    )
    if has_mentions:
        graph: nx.DiGraph | nx.Graph = nx.DiGraph()
    else:
        graph = nx.Graph()

    if user_edges.empty:
        return graph

    for _, row in user_edges.iterrows():
        src, tgt = row["source"], row["target"]
        weight = float(row.get("weight", 1))
        edge_type = str(row.get("edge_type", ""))
        if edge_type.startswith("mention") and isinstance(graph, nx.DiGraph):
            graph.add_edge(src, tgt, weight=weight)
        elif edge_type == "co_comment":
            if isinstance(graph, nx.DiGraph):
                graph.add_edge(src, tgt, weight=weight)
                graph.add_edge(tgt, src, weight=weight)
            else:
                graph.add_edge(src, tgt, weight=weight)
        elif isinstance(graph, nx.DiGraph):
            graph.add_edge(src, tgt, weight=weight)
        else:
            graph.add_edge(src, tgt, weight=weight)

    return graph


def export_network_metrics(
    hashtag_nodes: pd.DataFrame,
    hashtag_edges: pd.DataFrame,
    user_edges: pd.DataFrame,
    output_path: Path,
) -> pd.DataFrame:
    """Exporta métricas de hashtags y usuarios a network_metrics.csv."""
    rows: list[dict[str, Any]] = []

    hashtag_graph = build_hashtag_metric_graph(hashtag_nodes, hashtag_edges)
    rows.extend(
        _metrics_for_graph(
            hashtag_graph,
            "hashtags",
            directed=False,
            compute_eigenvector=True,
        )
    )

    user_graph = build_user_metric_graph(user_edges)
    rows.extend(
        _metrics_for_graph(
            user_graph,
            "users",
            directed=isinstance(user_graph, nx.DiGraph),
            compute_eigenvector=False,
        )
    )

    metrics_df = pd.DataFrame(rows, columns=METRIC_COLUMNS)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_df.to_csv(output_path, index=False, encoding="utf-8")
    return metrics_df
