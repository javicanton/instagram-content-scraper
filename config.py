"""Carga de configuración desde variables de entorno y .env."""

from __future__ import annotations

import os
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_COOKIE_FILE = PROJECT_ROOT / "instagram_cookie.txt"
DEFAULT_HASHTAGS_FILE = PROJECT_ROOT / "hashtags.csv"
EXAMPLE_HASHTAGS_FILE = PROJECT_ROOT / "hashtags.example.csv"

# Legacy: listas de ejemplo del caso de estudio académico (ver examples/)
EXAMPLE_HASHTAGS_MANOSFERA = PROJECT_ROOT / "examples" / "hashtags_manosfera.csv"
EXAMPLE_HASHTAGS_VIOLENCIA = PROJECT_ROOT / "examples" / "hashtags_violencia.csv"

DUAL_CORPUS_FILES: tuple[tuple[str, Path], ...] = (
    ("manosfera", EXAMPLE_HASHTAGS_MANOSFERA),
    ("violencia", EXAMPLE_HASHTAGS_VIOLENCIA),
)


def _read_cookie_file(path: Path) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    # Ignorar líneas de comentario; unir si el usuario partió en varias líneas
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return " ".join(lines).strip().strip('"').strip("'")


def _cookie_value(cookie: str, name: str) -> str:
    match = re.search(rf"(?:^|;\s*){re.escape(name)}=([^;]*)", cookie, re.I)
    return match.group(1).strip() if match else ""


def _load_instagram_cookie() -> str:
    file_path = os.getenv("INSTAGRAM_COOKIE_FILE", "").strip()
    cookie_path = Path(file_path) if file_path else DEFAULT_COOKIE_FILE
    from_file = _read_cookie_file(cookie_path)
    if from_file:
        return from_file
    return os.getenv("INSTAGRAM_COOKIE", "").strip().strip('"').strip("'")


@dataclass(frozen=True)
class Settings:
    instagram_session_id: str
    instagram_csrf_token: str
    instagram_cookie: str
    instatouch_timeout_ms: int
    delay_between_posts_sec: float
    delay_between_comment_jobs_sec: float
    max_retries: int
    raw_dir: Path
    output_dir: Path
    seeds_dir: Path
    history_dir: Path
    explore_variant: str

    @property
    def explore_referer(self) -> str:
        if self.explore_variant:
            return f"https://www.instagram.com/explore/?variant={self.explore_variant}"
        return "https://www.instagram.com/explore/"

    def hashtag_explore_url(self, tag: str) -> str:
        tag = tag.lstrip("#").strip()
        base = f"https://www.instagram.com/explore/tags/{urllib.parse.quote(tag)}/"
        if self.explore_variant:
            return f"{base}?variant={self.explore_variant}"
        return base

    @property
    def session_cookie(self) -> str:
        if self.instagram_cookie:
            return self.instagram_cookie
        parts = [f"sessionid={self.instagram_session_id}"]
        if self.instagram_csrf_token:
            token = self.instagram_csrf_token
            if not token.lower().startswith("csrftoken="):
                token = f"csrftoken={token}"
            parts.append(token)
        return "; ".join(parts)

    @property
    def csrf_token(self) -> str:
        if self.instagram_csrf_token:
            return self.instagram_csrf_token.lstrip("csrftoken=").strip()
        if self.instagram_cookie:
            return _cookie_value(self.instagram_cookie, "csrftoken")
        return ""


def load_settings(
    output_dir: Path | None = None,
    raw_dir: Path | None = None,
) -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    instagram_cookie = _load_instagram_cookie()
    session_id = os.getenv("INSTAGRAM_SESSION_ID", "").strip()
    csrf = os.getenv("INSTAGRAM_CSRF_TOKEN", "").strip()

    if instagram_cookie:
        if not session_id:
            session_id = _cookie_value(instagram_cookie, "sessionid")
        if not csrf:
            csrf = _cookie_value(instagram_cookie, "csrftoken")

    if not session_id and not instagram_cookie:
        raise ValueError(
            "Falta autenticación de Instagram.\n"
            "Opción A (recomendada): pega la cookie en instagram_cookie.txt (una línea).\n"
            "Opción B: define INSTAGRAM_SESSION_ID en .env.\n"
            "No uses INSTAGRAM_COOKIE= en .env si la cookie lleva comillas internas."
        )

    return Settings(
        instagram_session_id=session_id,
        instagram_csrf_token=csrf,
        instagram_cookie=instagram_cookie,
        instatouch_timeout_ms=int(os.getenv("INSTATOUCH_TIMEOUT_MS", "2000")),
        delay_between_posts_sec=float(os.getenv("DELAY_BETWEEN_POSTS_SEC", "1.5")),
        delay_between_comment_jobs_sec=float(
            os.getenv("DELAY_BETWEEN_COMMENT_JOBS_SEC", "2.0")
        ),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        raw_dir=raw_dir or PROJECT_ROOT / "data" / "raw",
        output_dir=output_dir or PROJECT_ROOT / "data" / "output",
        seeds_dir=PROJECT_ROOT / "data" / "seeds",
        history_dir=PROJECT_ROOT / ".history",
        explore_variant=os.getenv("INSTAGRAM_EXPLORE_VARIANT", "nonpersonalized").strip(),
    )
