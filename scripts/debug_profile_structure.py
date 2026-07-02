#!/usr/bin/env python3
"""Guarda estructura de respuesta IG para depuración (sin imprimir cookies)."""

from __future__ import annotations

import json
from pathlib import Path

from config import load_settings
from instagram_web_api import _request_json, _extract_edges

OUT = Path(__file__).resolve().parent.parent / "data" / "raw" / "debug_profile_structure.json"


def _summarize(obj, depth=0, max_depth=3):
    if depth >= max_depth:
        return type(obj).__name__
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in {"profile_pic_url", "hd_profile_pic_url_info", "biography"}:
                out[k] = "..."
            elif isinstance(v, dict) and "edges" in v:
                out[k] = {
                    "count": v.get("count"),
                    "edges_len": len(v.get("edges") or []),
                }
            else:
                out[k] = _summarize(v, depth + 1, max_depth)
        return out
    if isinstance(obj, list):
        return f"list[{len(obj)}]"
    return obj


def main():
    settings = load_settings()
    url = "https://i.instagram.com/api/v1/users/web_profile_info/?username=natgeo"
    payload = _request_json(url, settings)
    user = (payload.get("data") or {}).get("user") or {}
    edges = _extract_edges(user)
    summary = {
        "status": payload.get("status"),
        "username": user.get("username"),
        "user_keys": sorted(user.keys()),
        "user_summary": _summarize(user),
        "extracted_edges": len(edges),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Guardado: {OUT}")
    print(f"user keys: {len(summary['user_keys'])}")
    print(f"extracted edges: {summary['extracted_edges']}")


if __name__ == "__main__":
    main()
