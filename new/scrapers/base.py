"""Shared scraping infrastructure.

Every scraper in this package uses this client. It exists so that politeness,
caching, and provenance are not re-implemented (or forgotten) per source.

Rules encoded here, from CLAUDE.md:
  - rate limit every request
  - identify ourselves with a contact address
  - cache on disk; never re-fetch what hasn't changed
  - write a manifest next to every capture
  - raw captures are immutable
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
CACHE_DIR = REPO_ROOT / ".cache"

DEFAULT_UA = (
    "NE-Connect/0.1 (Nebraska public records index for journalists; "
    "set NE_CONNECT_UA with your contact address)"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Capture:
    """One scraper run's output directory."""

    source: str
    run_date: str
    dir: Path
    files: list[Path] = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    def add(self, filename: str, content: bytes | str) -> Path:
        path = self.dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            path.write_text(content, encoding="utf-8")
        else:
            path.write_bytes(content)
        self.files.append(path)
        return path

    def write_manifest(self, source_urls: list[str], row_count: int | None = None):
        manifest = {
            "source": self.source,
            "retrieved_at": utc_now(),
            "source_urls": source_urls,
            "row_count": row_count,
            "files": [
                {
                    "name": p.name,
                    "bytes": p.stat().st_size,
                    "sha256": sha256_file(p),
                }
                for p in self.files
            ],
            "notes": self.notes,
        }
        (self.dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        return manifest


class PoliteClient:
    """HTTP client with rate limiting, retry, and an on-disk cache.

    `min_interval` is seconds between requests to the same host. Default is
    deliberately slow. State servers are small; do not hammer them.
    """

    def __init__(
        self,
        min_interval: float = 1.5,
        timeout: float = 60.0,
        max_retries: int = 4,
        cache_dir: Path = CACHE_DIR,
    ):
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_request: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": os.environ.get("NE_CONNECT_UA", DEFAULT_UA)},
        )

    def _wait(self, url: str) -> None:
        host = urlparse(url).netloc
        last = self._last_request.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
        self._last_request[host] = time.monotonic()

    def _cache_path(self, url: str, body: str | None) -> Path:
        key = hashlib.sha256(f"{url}|{body or ''}".encode()).hexdigest()[:24]
        return self.cache_dir / f"{key}.bin"

    def get(self, url: str, use_cache: bool = True, **kwargs) -> bytes:
        cache_path = self._cache_path(url, None)
        if use_cache and cache_path.exists():
            return cache_path.read_bytes()

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            self._wait(url)
            try:
                resp = self._client.get(url, **kwargs)
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code}", request=resp.request, response=resp
                    )
                resp.raise_for_status()
                cache_path.write_bytes(resp.content)
                return resp.content
            except Exception as exc:  # noqa: BLE001 - retried and re-raised below
                last_error = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"failed after {self.max_retries} attempts: {url}") from last_error

    def close(self) -> None:
        self._client.close()


class Scraper:
    """Base class. Subclass per source and implement `run`.

    Subclasses must:
      - set `source` to the key used in docs/DATA_SOURCES.md and status.json
      - collect every URL they fetch into `self.source_urls`
      - write everything through `capture.add`
      - never mutate a previous capture
    """

    source: str = "unset"

    def __init__(self, client: PoliteClient | None = None):
        self.client = client or PoliteClient()
        self.source_urls: list[str] = []

    def new_capture(self) -> Capture:
        run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = RAW_DIR / self.source / run_date
        path.mkdir(parents=True, exist_ok=True)
        return Capture(source=self.source, run_date=run_date, dir=path)

    def fetch(self, url: str, **kwargs) -> bytes:
        self.source_urls.append(url)
        return self.client.get(url, **kwargs)

    def run(self) -> Capture:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def execute(self) -> dict:
        """Run and report status. Failures are loud and never silently stale."""
        try:
            capture = self.run()
            manifest = capture.write_manifest(sorted(set(self.source_urls)))
            return {
                "source": self.source,
                "ok": True,
                "retrieved_at": manifest["retrieved_at"],
                "row_count": manifest.get("row_count"),
            }
        except Exception as exc:  # noqa: BLE001 - surfaced to status.json
            return {
                "source": self.source,
                "ok": False,
                "failed_at": utc_now(),
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            self.client.close()
