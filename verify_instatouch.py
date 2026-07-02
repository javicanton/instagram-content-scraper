#!/usr/bin/env python3
"""Comprueba sesión de Instagram; diagnostica instatouch vs API web."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from config import DEFAULT_COOKIE_FILE, load_settings
from instagram_web_api import fetch_user_posts

PROJECT_ROOT = Path(__file__).resolve().parent


def _validate_auth(session_id: str, cookie_file: Path) -> list[str]:
    issues = []
    if DEFAULT_COOKIE_FILE.exists():
        size = DEFAULT_COOKIE_FILE.stat().st_size
        if size < 50:
            issues.append(f"{DEFAULT_COOKIE_FILE.name} existe pero parece vacío.")
        return issues

    if not session_id or session_id in {"tu_session_id_aqui", "XXXXXXXX"}:
        issues.append(
            f"No hay {DEFAULT_COOKIE_FILE.name} ni INSTAGRAM_SESSION_ID válido."
        )
    elif len(session_id) < 20:
        issues.append("INSTAGRAM_SESSION_ID parece demasiado corto.")
    return issues


def _diag_instatouch(timeout_sec: int = 15) -> tuple[bool, int, str]:
    """Prueba instatouch legacy; puede colgar o tardar mucho (GraphQL obsoleto)."""
    script = PROJECT_ROOT / "scripts" / "diag_instatouch.js"
    env = os.environ.copy()
    env["NODE_NO_WARNINGS"] = "1"
    try:
        proc = subprocess.run(
            ["node", str(script)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        return False, 0, f"timeout ({timeout_sec}s) — instatouch colgado; ignóralo si la API web responde"

    out = (proc.stdout or "") + (proc.stderr or "")
    auth_error = "auth_error: true" in out
    m = re.search(r"collector length:\s*(\d+)", out)
    count = int(m.group(1)) if m else 0
    note = ""
    if proc.returncode != 0 and not out.strip():
        note = "sin salida de instatouch"
    return auth_error, count, note


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")

    print("=== Verificación Instagram ===\n")

    if DEFAULT_COOKIE_FILE.exists():
        print(f"Cookie: {DEFAULT_COOKIE_FILE.name} ({DEFAULT_COOKIE_FILE.stat().st_size} bytes)")
    else:
        print(f"Cookie: usa {DEFAULT_COOKIE_FILE.name} (recomendado)")

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    issues = _validate_auth(settings.instagram_session_id, DEFAULT_COOKIE_FILE)
    for msg in issues:
        print(f"ERROR: {msg}")

    print(f"Sessionid detectado: {'sí' if settings.instagram_session_id else 'no'}")
    print(f"CSRf detectado: {'sí' if settings.csrf_token else 'no'}")

    print("\n--- API web (fallback del proyecto; la que importa) ---")
    items, err = fetch_user_posts("natgeo", 3, settings)
    if items:
        print(f"  OK: {len(items)} posts de @natgeo")
        print(f"  Ejemplo: {items[0].get('url', '')}")
        web_ok = True
    else:
        print(f"  FALLO: {err or 'sin datos'}")
        web_ok = False

    print("\n--- instatouch (legacy, suele fallar o colgar) ---")
    auth_error, legacy_count, note = _diag_instatouch(timeout_sec=15)
    if note:
        print(f"  {note}")
    else:
        print(f"  auth_error: {auth_error}")
        print(f"  posts: {legacy_count}")
        if legacy_count == 0 and not auth_error:
            print("  → GraphQL de instatouch obsoleto (normal).")

    if web_ok:
        print("\n=== RESULTADO: sesión válida — listo para orchestrator.py ===")
        print("(instatouch puede ignorarse; el scraper usa API web cuando hace falta)")
        return 0

    print("\n=== Qué hacer ===")
    print(f"1. Borra INSTAGRAM_COOKIE= de .env (rompe el parser por comillas en rur=...)")
    print(f"2. Pega la cookie en {DEFAULT_COOKIE_FILE.name} (UNA línea, sin comillas externas)")
    print("3. Copia desde Chrome: Network → instagram.com → Request Headers → cookie:")
    print("4. Renueva la cookie si sigue fallando (sesión expirada)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
