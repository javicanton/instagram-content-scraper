#!/usr/bin/env python3
"""Regenera docs/graphs/ desde análisis de ejemplo o propio para GitHub Pages."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from export_graph_web import export_all_from_analysis, write_manifest

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ANALYSIS = PROJECT_ROOT / "examples" / "analysis"
DOCS_DIR = PROJECT_ROOT / "docs"
DOCS_GRAPHS = DOCS_DIR / "graphs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exporta grafos interactivos a docs/graphs/.")
    parser.add_argument(
        "--analysis-dir",
        default=str(DEFAULT_ANALYSIS),
        help="Directorio con subcarpetas por corpus (default: examples/analysis).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    analysis_root = Path(args.analysis_dir)
    if not analysis_root.exists():
        print(f"ERROR: no existe {analysis_root}", file=sys.stderr)
        return 1

    written: list[Path] = []
    for corpus_dir in sorted(analysis_root.iterdir()):
        if not corpus_dir.is_dir():
            continue
        files = export_all_from_analysis(corpus_dir, DOCS_GRAPHS)
        written.extend(files)
        print(f"  {corpus_dir.name}: {len(files)} grafos")

    if not written:
        print(
            f"AVISO: no se encontraron graph_hashtags_*.graphml en {analysis_root}/",
            file=sys.stderr,
        )
        return 1

    # Eliminar JSON legacy (users, nombres antiguos)
    for stale in DOCS_GRAPHS.glob("users_*.json"):
        stale.unlink()
    for stale in DOCS_GRAPHS.glob("hashtags_manosfera.json"):
        if not any(p.name == "hashtags_manosfera.json" for p in written):
            stale.unlink()
    for stale in DOCS_GRAPHS.glob("manosfera.json"):
        stale.unlink()
    for stale in DOCS_GRAPHS.glob("violencia.json"):
        stale.unlink()

    manifest = write_manifest(DOCS_DIR, written)
    print(f"Manifest: {manifest}")
    print(f"Total: {len(written)} grafos → {DOCS_GRAPHS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
