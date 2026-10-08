"""Polite HTTP fetching for small municipal servers.

Rules enforced here: a descriptive User-Agent, robots.txt respected (including
Crawl-delay), a minimum delay between any two requests to the same process,
conditional requests (ETag / Last-Modified), cached files are never fetched
again unless the caller asks to revalidate, and a hard stop on 429 or 5xx.
"""
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "EchoDeMontolieu/0.1 (civic transparency project; "
    "+https://github.com/mgifford/EchoDeMontolieu)"
)
DEFAULT_MIN_DELAY = 10.0


class StopFetching(Exception):
    """Raised on 429 or 5xx so callers stop instead of retrying."""


@dataclass
class Fetched:
    url: str
    path: Path
    status: str  # "fetched", "not_modified" or "cached"
    retrieved_at: str  # when the content was last actually downloaded
    sha256: str
    etag: str = None  # HTTP validators as last seen from the server
    last_modified: str = None


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PoliteFetcher:
    def __init__(self, cache_dir, min_delay=DEFAULT_MIN_DELAY, session=None,
                 sleep=time.sleep, clock=time.monotonic):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_delay = min_delay
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        # Requests are seconds apart, so keep-alive gains nothing, and a server that
        # closes idle connections would break the reused one.
        self.session.headers["Connection"] = "close"
        self._sleep = sleep
        self._clock = clock
        self._last_request = None
        self._robots = {}
        self._index_path = self.cache_dir / "index.json"
        self._index = (json.loads(self._index_path.read_text())
                       if self._index_path.exists() else {})

    def _wait(self, delay):
        if self._last_request is not None:
            remaining = delay - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)

    def _request(self, url, headers=None, delay=None):
        self._wait(self.min_delay if delay is None else delay)
        try:
            return self.session.get(url, headers=headers or {}, timeout=30)
        except requests.RequestException as exc:
            raise StopFetching(f"network error for {url}: {exc!r}") from exc
        finally:
            self._last_request = self._clock()

    def _robots_for(self, url):
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = robotparser.RobotFileParser()
            resp = self._request(f"{origin}/robots.txt")
            # A missing or unreadable robots.txt is treated as "no rules".
            rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            self._robots[origin] = rp
        return self._robots[origin]

    def _save_index(self):
        self._index_path.write_text(json.dumps(self._index, indent=2))

    def get(self, url, revalidate=True):
        rp = self._robots_for(url)
        if not rp.can_fetch(USER_AGENT, url):
            raise PermissionError(f"robots.txt disallows {url}")
        crawl_delay = rp.crawl_delay(USER_AGENT)
        delay = max(self.min_delay, float(crawl_delay or 0))

        entry = self._index.get(url)
        cached = entry and Path(entry["path"]).exists()
        if cached and not revalidate:
            return Fetched(url, Path(entry["path"]), "cached", entry["retrieved_at"],
                           entry["sha256"], entry.get("etag"), entry.get("last_modified"))

        headers = {}
        if cached:
            if entry.get("etag"):
                headers["If-None-Match"] = entry["etag"]
            if entry.get("last_modified"):
                headers["If-Modified-Since"] = entry["last_modified"]

        resp = self._request(url, headers, delay)
        if resp.status_code == 304 and cached:
            return Fetched(url, Path(entry["path"]), "not_modified", entry["retrieved_at"],
                           entry["sha256"], entry.get("etag"), entry.get("last_modified"))
        if resp.status_code == 429 or resp.status_code >= 500:
            raise StopFetching(
                f"{resp.status_code} from {url} "
                f"(Retry-After: {resp.headers.get('Retry-After')})")
        resp.raise_for_status()

        digest = hashlib.sha256(resp.content).hexdigest()
        suffix = Path(urlparse(url).path).suffix or ".html"
        path = self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}{suffix}"
        path.write_bytes(resp.content)
        self._index[url] = {
            "path": str(path),
            "etag": resp.headers.get("ETag"),
            "last_modified": resp.headers.get("Last-Modified"),
            "retrieved_at": _now(),
            "sha256": digest,
        }
        self._save_index()
        return Fetched(url, path, "fetched", self._index[url]["retrieved_at"], digest,
                       self._index[url]["etag"], self._index[url]["last_modified"])
