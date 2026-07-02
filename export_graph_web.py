#!/usr/bin/env python3
"""Exporta grafos GraphML a JSON interactivo para GitHub Pages (vis-network)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import networkx as nx

NODE_COLORS = {
    "hashtag": "#e1306c",
    "user": "#405de6",
    "profile": "#833ab4",
    "narrative": "#fd5949",
    "default": "#999999",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convierte graph_*.graphml a JSON para el visor web en docs/."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Ruta al archivo .graphml (p. ej. data/analysis/violencia/graph_hashtags_violencia.graphml).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="JSON de salida (default: docs/graphs/<stem>.json).",
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=200,
        help="Máximo de nodos (por grado). 0 = sin límite.",
    )
    parser.add_argument(
        "--min-edge-weight",
        type=float,
        default=1.0,
        help="Peso mínimo de arista tras filtrar nodos.",
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
    parser.add_argument(
        "--graph-type",
        default="",
        help="Tipo de grafo: hashtags, users, full (metadato).",
    )
    return parser.parse_args()


def _node_label(node_id: str, attrs: dict) -> str:
    label = str(attrs.get("label", "") or "").strip()
    if label:
        return label
    if ":" in node_id:
        return node_id.split(":", 1)[1]
    return node_id


def _node_group(attrs: dict) -> str:
    return str(attrs.get("node_type", "") or "default").strip() or "default"


def _node_size(attrs: dict) -> float:
    for key in ("post_count", "n_comments", "degree"):
        raw = attrs.get(key, "")
        try:
            value = float(raw)
            if value > 0:
                return max(8.0, min(40.0, 6.0 + value ** 0.5))
        except (TypeError, ValueError):
            continue
    return 12.0


def filter_graph(
    graph: nx.Graph,
    *,
    max_nodes: int,
    min_edge_weight: float,
) -> nx.Graph:
    if max_nodes <= 0 or graph.number_of_nodes() <= max_nodes:
        subgraph = graph.copy()
    else:
        ranked = sorted(
            graph.degree(weight="weight"),
            key=lambda item: item[1],
            reverse=True,
        )
        keep = {node for node, _ in ranked[:max_nodes]}
        subgraph = graph.subgraph(keep).copy()

    if min_edge_weight > 1.0:
        remove = [
            (u, v)
            for u, v, data in subgraph.edges(data=True)
            if float(data.get("weight", 1)) < min_edge_weight
        ]
        subgraph.remove_edges_from(remove)
        isolates = list(nx.isolates(subgraph))
        subgraph.remove_nodes_from(isolates)

    return subgraph


def graph_to_vis_json(
    graph: nx.Graph,
    *,
    title: str,
    corpus_id: str,
    graph_type: str,
    source_path: Path,
) -> dict:
    nodes = []
    for node_id, attrs in graph.nodes(data=True):
        group = _node_group(attrs)
        nodes.append(
            {
                "id": node_id,
                "label": _node_label(node_id, attrs),
                "group": group,
                "color": NODE_COLORS.get(group, NODE_COLORS["default"]),
                "size": _node_size(attrs),
                "title": "<br>".join(
                    f"{k}: {v}" for k, v in sorted(attrs.items()) if str(v).strip()
                ),
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
                "title": f"{attrs.get('edge_type', 'edge')}: {weight}",
            }
        )

    return {
        "title": title or source_path.stem,
        "corpus_id": corpus_id,
        "graph_type": graph_type,
        "source": source_path.name,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
    }


def default_output_path(input_path: Path, output_dir: Path) -> Path:
    stem = input_path.stem
    if stem.startswith("graph_"):
        stem = stem[len("graph_") :]
    return output_dir / f"{stem}.json"


def export_graph(
    input_path: Path,
    output_path: Path,
    *,
    max_nodes: int,
    min_edge_weight: float,
    title: str,
    corpus_id: str,
    graph_type: str,
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    graph = nx.read_graphml(input_path)
    filtered = filter_graph(graph, max_nodes=max_nodes, min_edge_weight=min_edge_weight)
    payload = graph_to_vis_json(
        filtered,
        title=title,
        corpus_id=corpus_id,
        graph_type=graph_type,
        source_path=input_path,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return output_path


def export_all_from_analysis(
    analysis_dir: Path,
    docs_graphs_dir: Path,
    *,
    max_nodes: int = 200,
) -> list[Path]:
    """Exporta graph_hashtags_*, graph_users_* y graph_* de un directorio de análisis."""
    written: list[Path] = []

    for graphml in sorted(analysis_dir.glob("graph*.graphml")):
        stem = graphml.stem
        if "_hashtags_" in stem:
            graph_type = "hashtags"
        elif "_users_" in stem:
            graph_type = "users"
        elif stem.startswith("graph_"):
            graph_type = "full"
        else:
            graph_type = "graph"

        corpus_id = stem.split("_")[-1]
        out = default_output_path(graphml, docs_graphs_dir)
        title = f"{corpus_id} — {graph_type}"

        written.append(
            export_graph(
                graphml,
                out,
                max_nodes=max_nodes,
                min_edge_weight=1.0,
                title=title,
                corpus_id=corpus_id,
                graph_type=graph_type,
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
                "graph_type": data.get("graph_type", ""),
                "node_count": data.get("node_count", 0),
                "edge_count": data.get("edge_count", 0),
            }
        )
    manifest = {"graphs": graphs}
    manifest_path = docs_dir / "graphs" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = (
        Path(args.output)
        if args.output
        else default_output_path(input_path, Path("docs/graphs"))
    )

    try:
        out = export_graph(
            input_path,
            output_path,
            max_nodes=args.max_nodes,
            min_edge_weight=args.min_edge_weight,
            title=args.title,
            corpus_id=args.corpus_id,
            graph_type=args.graph_type,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Grafo web: {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
