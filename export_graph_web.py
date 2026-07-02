#!/usr/bin/env python3
"""Exporta grafos GraphML a JSON interactivo para GitHub Pages (vis-network)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import networkx as nx

# Grado mínimo por corpus (equivalente a Gephi: grado ≥ umbral)
CORPUS_DEFAULT_MIN_DEGREE: dict[str, int] = {
    "manosfera": 33,
    "violencia": 30,
}

CLUSTER_PALETTE = [
    "#e1306c",
    "#405de6",
    "#833ab4",
    "#fd5949",
    "#f77737",
    "#fcaf45",
    "#00b894",
    "#0984e3",
    "#6c5ce7",
    "#e17055",
    "#00cec9",
    "#d63031",
    "#2d3436",
    "#a29bfe",
    "#55efc4",
    "#ffeaa7",
    "#81ecec",
    "#fab1a0",
    "#74b9ff",
    "#636e72",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convierte graph_hashtags_*.graphml a JSON para el visor web en docs/."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Ruta al archivo .graphml.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="JSON de salida (default: docs/graphs/<stem>.json).",
    )
    parser.add_argument(
        "--min-degree",
        type=int,
        default=None,
        help="Grado mínimo por defecto en el visor (≥). Auto por corpus si se omite.",
    )
    parser.add_argument(
        "--title",
        default="",
        help="Título legible para el visor.",
    )
    parser.add_argument(
        "--corpus-id",
        default="",
        help="ID del corpus (metadato en el JSON).",
    )
    return parser.parse_args()


def _node_label(node_id: str, attrs: dict) -> str:
    label = str(attrs.get("label", "") or "").strip()
    if label:
        return label
    if ":" in node_id:
        return f"#{node_id.split(':', 1)[1]}"
    return node_id


def _post_count(attrs: dict) -> int:
    raw = attrs.get("post_count", attrs.get("sourced_posts", 0))
    try:
        value = float(raw)
        if value != value:  # NaN
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _node_size(degree: int, post_count: int) -> float:
    base = max(degree, post_count, 1)
    return max(8.0, min(36.0, 6.0 + base ** 0.45))


def _color_for_community(community_id: str | int) -> str:
    try:
        idx = int(community_id) % len(CLUSTER_PALETTE)
    except (TypeError, ValueError):
        idx = hash(str(community_id)) % len(CLUSTER_PALETTE)
    return CLUSTER_PALETTE[idx]


def _color_for_narrative_cluster(cluster_id: str) -> str:
    text = str(cluster_id or "").strip()
    if not text or text.lower() == "nan":
        return CLUSTER_PALETTE[-1]
    try:
        return CLUSTER_PALETTE[int(text) % len(CLUSTER_PALETTE)]
    except ValueError:
        return CLUSTER_PALETTE[hash(text) % len(CLUSTER_PALETTE)]


def detect_communities(graph: nx.Graph) -> dict[str, str]:
    if graph.number_of_nodes() == 0:
        return {}
    communities = nx.community.louvain_communities(graph, weight="weight", seed=0)
    out: dict[str, str] = {}
    for idx, comm in enumerate(communities):
        for node in comm:
            out[str(node)] = str(idx)
    return out


def enrich_narrative_colors(graph: nx.Graph, communities: dict[str, str]) -> dict[str, str]:
    """Usa cluster_id del graphml en nodos narrative; Louvain para hashtags."""
    out = dict(communities)
    for node_id, attrs in graph.nodes(data=True):
        node_type = str(attrs.get("node_type", "") or "")
        if node_type == "narrative":
            cid = str(attrs.get("cluster_id", "") or "").strip()
            if cid and cid.lower() != "nan":
                out[node_id] = f"narrative_{cid}"
    return out


def graph_to_vis_json(
    graph: nx.Graph,
    *,
    title: str,
    corpus_id: str,
    source_path: Path,
    default_min_degree: int,
) -> dict:
    communities = detect_communities(graph)
    communities = enrich_narrative_colors(graph, communities)

    degrees = dict(graph.degree())
    max_degree = max(degrees.values()) if degrees else 0

    nodes = []
    for node_id, attrs in graph.nodes(data=True):
        node_type = str(attrs.get("node_type", "hashtag") or "hashtag")
        degree = int(degrees.get(node_id, 0))
        post_count = _post_count(attrs)
        label = _node_label(node_id, attrs)

        if node_type == "narrative":
            cluster_id = str(attrs.get("cluster_id", "") or "").strip()
            community_id = f"narrative_{cluster_id}" if cluster_id else communities.get(node_id, "0")
            color = _color_for_narrative_cluster(cluster_id or community_id)
        else:
            community_id = communities.get(node_id, "0")
            color = _color_for_community(community_id)

        nodes.append(
            {
                "id": node_id,
                "label": label,
                "node_type": node_type,
                "group": node_type,
                "degree": degree,
                "post_count": post_count,
                "community_id": community_id,
                "cluster_id": str(attrs.get("cluster_id", "") or ""),
                "color": color,
                "size": _node_size(degree, post_count),
            }
        )

    edges = []
    for source, target, attrs in graph.edges(data=True):
        weight = float(attrs.get("weight", 1))
        edges.append(
            {
                "from": source,
                "to": target,
                "value": max(1.0, weight),
                "edge_type": str(attrs.get("edge_type", "edge")),
            }
        )

    community_ids = sorted({n["community_id"] for n in nodes})

    return {
        "title": title or source_path.stem,
        "corpus_id": corpus_id,
        "graph_type": "hashtags",
        "source": source_path.name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "defaults": {
            "min_degree": default_min_degree,
            "min_edge_weight": 1,
            "show_labels": True,
            "node_types": ["hashtag"],
        },
        "filters": {
            "degree_min": 0,
            "degree_max": max_degree,
            "edge_weight_min": 1,
            "edge_weight_max": max(
                (int(e["value"]) for e in edges),
                default=1,
            ),
        },
        "community_count": len(community_ids),
        "nodes": nodes,
        "edges": edges,
    }


def default_output_path(input_path: Path, output_dir: Path) -> Path:
    stem = input_path.stem
    if stem.startswith("graph_hashtags_"):
        stem = stem[len("graph_hashtags_") :]
    elif stem.startswith("graph_"):
        stem = stem[len("graph_") :]
    return output_dir / f"hashtags_{stem}.json"


def resolve_min_degree(corpus_id: str, explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    return CORPUS_DEFAULT_MIN_DEGREE.get(corpus_id, 1)


def export_graph(
    input_path: Path,
    output_path: Path,
    *,
    min_degree: int | None,
    title: str,
    corpus_id: str,
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    graph = nx.read_graphml(input_path)
    default_min = resolve_min_degree(corpus_id, min_degree)
    payload = graph_to_vis_json(
        graph,
        title=title,
        corpus_id=corpus_id,
        source_path=input_path,
        default_min_degree=default_min,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return output_path


def export_all_from_analysis(
    analysis_dir: Path,
    docs_graphs_dir: Path,
    *,
    min_degree: int | None = None,
) -> list[Path]:
    """Exporta solo graph_hashtags_<corpus>.graphml (sin grafos de usuarios)."""
    written: list[Path] = []

    for graphml in sorted(analysis_dir.glob("graph_hashtags_*.graphml")):
        corpus_id = graphml.stem.split("_")[-1]
        out = default_output_path(graphml, docs_graphs_dir)
        title = f"Hashtags — {corpus_id}"

        written.append(
            export_graph(
                graphml,
                out,
                min_degree=min_degree if min_degree is not None else resolve_min_degree(corpus_id, None),
                title=title,
                corpus_id=corpus_id,
            )
        )
    return written


def write_manifest(docs_dir: Path, graph_files: list[Path]) -> Path:
    graphs = []
    for path in sorted(graph_files):
        data = json.loads(path.read_text(encoding="utf-8"))
        graphs.append(
            {
                "id": path.stem,
                "file": f"graphs/{path.name}",
                "title": data.get("title", path.stem),
                "corpus_id": data.get("corpus_id", ""),
                "graph_type": data.get("graph_type", "hashtags"),
                "node_count": data.get("node_count", 0),
                "edge_count": data.get("edge_count", 0),
                "defaults": data.get("defaults", {}),
                "community_count": data.get("community_count", 0),
            }
        )
    manifest = {"graphs": graphs}
    manifest_path = docs_dir / "graphs" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    corpus_id = args.corpus_id or input_path.stem.split("_")[-1]
    output_path = (
        Path(args.output)
        if args.output
        else default_output_path(input_path, Path("docs/graphs"))
    )

    try:
        out = export_graph(
            input_path,
            output_path,
            min_degree=args.min_degree,
            title=args.title,
            corpus_id=corpus_id,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Grafo web: {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
