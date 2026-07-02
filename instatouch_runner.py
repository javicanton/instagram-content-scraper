"""Wrapper subprocess para invocar instatouch (npm)."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from config import PROJECT_ROOT, Settings
from instagram_web_api import (
    fetch_hashtag_posts,
    fetch_post_comments,
    fetch_user_posts,
    save_collector_json,
    save_comments_json,
)


@dataclass
class InstatouchResult:
    success: bool
    csv_path: Path | None
    json_path: Path | None
    stdout: str
    stderr: str
    returncode: int


class InstatouchRunner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.raw_dir.mkdir(parents=True, exist_ok=True)
        self.settings.history_dir.mkdir(parents=True, exist_ok=True)
        self._binary = self._resolve_binary()

    def _resolve_binary(self) -> list[str]:
        local_cli = PROJECT_ROOT / "node_modules" / ".bin" / "instatouch"
        if local_cli.exists():
            return [str(local_cli)]
        return ["npx", "instatouch"]

    def _base_args(self) -> list[str]:
        return [
            "--session",
            self.settings.session_cookie,
            "--timeout",
            str(self.settings.instatouch_timeout_ms),
            "--filepath",
            str(self.settings.raw_dir),
            "--historypath",
            str(self.settings.history_dir),
        ]

    def _run_with_retries(self, args: list[str]) -> InstatouchResult:
        last_result: InstatouchResult | None = None
        for attempt in range(self.settings.max_retries):
            if attempt > 0:
                backoff = 2**attempt
                print(f"  Reintento {attempt + 1}/{self.settings.max_retries} (espera {backoff}s)...")
                time.sleep(backoff)

            result = self._run_once(args)
            last_result = result

            if result.success and result.csv_path and result.csv_path.exists():
                return result

            combined = f"{result.stdout}\n{result.stderr}".lower()
            if "rate limit" in combined or "429" in combined:
                wait = max(self.settings.instatouch_timeout_ms / 1000, 5)
                print(f"  Rate limit detectado, esperando {wait}s...")
                time.sleep(wait)
                continue

            if result.returncode == 0 and result.csv_path and result.csv_path.exists():
                return result

        assert last_result is not None
        return last_result

    def _run_once(self, args: list[str]) -> InstatouchResult:
        cmd = self._binary + args
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        csv_path = self._extract_path(stdout, "CSV path:")
        json_path = self._extract_path(stdout, "JSON path:")

        if not csv_path:
            csv_path = self._find_expected_csv(args)

        json_path = json_path or self._find_expected_json(args)

        expected_csv = self._find_expected_csv(args)
        success = (
            proc.returncode == 0
            and expected_csv is not None
            and expected_csv.exists()
            and expected_csv.stat().st_size > 0
        )
        if success:
            csv_path = expected_csv
        elif csv_path and csv_path != expected_csv:
            csv_path = None
            success = False
        return InstatouchResult(
            success=success,
            csv_path=csv_path,
            json_path=json_path,
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode,
        )

    @staticmethod
    def _extract_path(stdout: str, prefix: str) -> Path | None:
        for line in stdout.splitlines():
            if line.strip().startswith(prefix):
                return Path(line.split(":", 1)[1].strip())
        return None

    def _find_expected_csv(self, args: list[str]) -> Path | None:
        filename = self._filename_from_args(args)
        if not filename:
            return None
        candidate = self.settings.raw_dir / f"{filename}.csv"
        return candidate if candidate.exists() else None

    def _find_expected_json(self, args: list[str]) -> Path | None:
        filename = self._filename_from_args(args)
        if not filename:
            return None
        candidate = self.settings.raw_dir / f"{filename}.json"
        return candidate if candidate.exists() else None

    @staticmethod
    def _filename_from_args(args: list[str]) -> str | None:
        for i, arg in enumerate(args):
            if arg in ("--filename", "-f") and i + 1 < len(args):
                return args[i + 1]
        return None

    def _find_latest_csv(self, args: list[str]) -> Path | None:
        return self._find_expected_csv(args)

    def _fallback_user_via_web_api(
        self,
        username: str,
        count: int,
        fname: str,
    ) -> InstatouchResult:
        print("  instatouch sin datos → intentando API web de Instagram...")
        items, err = fetch_user_posts(username, count, self.settings)
        if err == "auth_error":
            print("  ERROR: sesión rechazada (401/403). Renueva INSTAGRAM_SESSION_ID.")
            return InstatouchResult(False, None, None, "", "auth_error", 1)
        if not items:
            msg = err or "empty_timeline"
            print(f"  ERROR: API web sin posts ({msg}).")
            if msg == "empty_timeline":
                print(
                    "  Añade INSTAGRAM_CSRF_TOKEN en .env (cookie csrftoken de Chrome) "
                    "y vuelve a probar."
                )
            return InstatouchResult(False, None, None, "", msg, 1)

        json_path, csv_path = save_collector_json(
            items, self.settings, filename=fname
        )
        print(f"  OK vía API web: {len(items)} posts → {csv_path}")
        return InstatouchResult(
            success=True,
            csv_path=csv_path,
            json_path=json_path,
            stdout=f"CSV path: {csv_path}",
            stderr="",
            returncode=0,
        )

    def scrape_user(
        self,
        username: str,
        count: int,
        *,
        use_store: bool = True,
        filename: str | None = None,
    ) -> InstatouchResult:
        stamp = int(time.time() * 1000)
        fname = filename or f"user_{username}_{stamp}"
        args = [
            "user",
            username,
            "-c",
            str(count),
            "-t",
            "all",
            "-f",
            fname,
            *self._base_args(),
        ]
        if use_store:
            args.append("--store")
        result = self._run_with_retries(args)

        ok = (
            result.success
            and result.csv_path
            and result.csv_path.exists()
            and result.csv_path.stat().st_size > 50
        )
        if ok:
            return result
        return self._fallback_user_via_web_api(username, count, fname)

    def _fallback_hashtag_via_web_api(
        self,
        tag: str,
        count: int,
        fname: str,
    ) -> InstatouchResult:
        print("  instatouch sin datos → intentando API web (hashtag)...")
        items, err = fetch_hashtag_posts(tag, count, self.settings)
        if err == "auth_error":
            print("  ERROR: sesión rechazada. Revisa instagram_cookie.txt")
            return InstatouchResult(False, None, None, "", "auth_error", 1)
        if not items:
            print(f"  ERROR: hashtag #{tag} sin posts ({err or 'vacío'}).")
            return InstatouchResult(False, None, None, "", err or "empty", 1)

        json_path, csv_path = save_collector_json(items, self.settings, filename=fname)
        print(f"  OK vía API web: {len(items)} posts → {csv_path}")
        return InstatouchResult(
            success=True,
            csv_path=csv_path,
            json_path=json_path,
            stdout=f"CSV path: {csv_path}",
            stderr="",
            returncode=0,
        )

    def scrape_hashtag(
        self,
        tag: str,
        count: int,
        *,
        use_store: bool = True,
        filename: str | None = None,
    ) -> InstatouchResult:
        tag = tag.lstrip("#")
        stamp = int(time.time() * 1000)
        fname = filename or f"hashtag_{tag}_{stamp}"
        args = [
            "hashtag",
            tag,
            "-c",
            str(count),
            "-t",
            "all",
            "-f",
            fname,
            *self._base_args(),
        ]
        if use_store:
            args.append("--store")
        result = self._run_with_retries(args)
        ok = (
            result.success
            and result.csv_path
            and result.csv_path.exists()
            and result.csv_path.stat().st_size > 50
        )
        if ok:
            return result
        return self._fallback_hashtag_via_web_api(tag, count, fname)

    def _fallback_comments_via_web_api(
        self,
        post_ref: str,
        count: int,
        fname: str,
        *,
        media_id: str | None = None,
    ) -> InstatouchResult:
        print("  instatouch sin comentarios → intentando API web de Instagram...")
        items, err = fetch_post_comments(
            post_ref, count, self.settings, media_id=media_id
        )
        if err == "auth_error":
            print("  ERROR: sesión rechazada. Revisa instagram_cookie.txt")
            return InstatouchResult(False, None, None, "", "auth_error", 1)
        if not items:
            if err in (None, "empty_comments"):
                json_path, csv_path = save_comments_json(
                    [], self.settings, filename=fname
                )
                print("  OK vía API web: 0 comentarios (post sin actividad)")
                return InstatouchResult(
                    success=True,
                    csv_path=csv_path,
                    json_path=json_path,
                    stdout=f"CSV path: {csv_path}\nJSON path: {json_path}",
                    stderr="",
                    returncode=0,
                )
            print(f"  ERROR: sin comentarios vía API web ({err or 'vacío'}).")
            return InstatouchResult(False, None, None, "", err or "empty_comments", 1)

        json_path, csv_path = save_comments_json(items, self.settings, filename=fname)
        with_text = sum(1 for item in items if str(item.get("text", "")).strip())
        print(f"  OK vía API web: {len(items)} comentarios ({with_text} con texto) → {csv_path}")
        return InstatouchResult(
            success=True,
            csv_path=csv_path,
            json_path=json_path,
            stdout=f"CSV path: {csv_path}\nJSON path: {json_path}",
            stderr="",
            returncode=0,
        )

    def scrape_comments(
        self,
        post_ref: str,
        count: int,
        *,
        filename: str | None = None,
        media_id: str | None = None,
    ) -> InstatouchResult:
        stamp = int(time.time() * 1000)
        safe_ref = re.sub(r"[^\w.-]", "_", post_ref)[:80]
        fname = filename or f"comments_{safe_ref}_{stamp}"
        args = [
            "comments",
            post_ref,
            "-c",
            str(count),
            "-t",
            "all",
            "-f",
            fname,
            *self._base_args(),
        ]
        result = self._run_with_retries(args)
        ok = (
            result.success
            and result.csv_path
            and result.csv_path.exists()
            and result.csv_path.name.startswith("comments_")
            and result.csv_path.stat().st_size > 20
        )
        if ok and result.json_path and result.json_path.exists():
            return result
        if ok:
            return result
        return self._fallback_comments_via_web_api(
            post_ref, count, fname, media_id=media_id
        )

    def scrape_from_file(self, seeds_file: Path, *, async_mode: bool = True) -> InstatouchResult:
        stamp = int(time.time() * 1000)
        fname = f"fromfile_{stamp}"
        args = [
            "from-file",
            str(seeds_file),
            *self._base_args(),
            "-t",
            "all",
            "-f",
            fname,
            "--store",
        ]
        if async_mode:
            args.append("async")
        return self._run_with_retries(args)
