"""fetch.py

Cached, rate-limited HTTP client for SEC EDGAR requests.

All outbound requests in Chapter 1 (CIK lookup file, submissions API,
archive directory listings, filing XML) go through fetch() rather than
calling httpx directly:

  1. SEC requires a User-Agent on every request.
  2. SEC caps clients at 10 req/sec; throttling is centralized here.
  3. The pipeline is run twice and the second run must be substantially
     faster with identical output; caching is centralized here so every
     caller gets cache-and-resume behavior automatically.

The User-Agent is not a module-level constant. main.py owns the
--user-agent CLI flag and calls set_user_agent() once at startup;
downstream modules under src/ call fetch(url) without repeating it.

Usage:
    from fetch import fetch, set_user_agent
    set_user_agent(args.user_agent)
    raw = fetch("https://data.sec.gov/submissions/CIK0001037389.json")
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

CACHE_DIR = Path("output/.cache")
MANIFEST_PATH = CACHE_DIR / "manifest.jsonl"

# SEC's limit is 10 req/sec; stay under it with margin.
MIN_INTERVAL_SECONDS = 1.0 / 8.0

# Exponential backoff on 429, bounded retry count.
INITIAL_BACKOFF_SECONDS = 2.0
MAX_RETRIES = 5

_last_request_monotonic = 0.0

# Unset until main.py calls set_user_agent(). fetch() fails fast if called
# beforehand rather than silently sending a blank or stale header.
_user_agent: str | None = None


def set_user_agent(user_agent: str) -> None:
    """Called once by the entry point after parsing --user-agent."""
    global _user_agent
    _user_agent = user_agent


def _require_user_agent() -> str:
    if not _user_agent:
        raise RuntimeError(
            "fetch() called before set_user_agent(). The entry point must "
            "call set_user_agent(args.user_agent) before any network access."
        )
    return _user_agent


def _cache_key(url: str) -> str:
    parsed = urlparse(url)
    readable = parsed.path.strip("/").replace("/", "_") or "root"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{readable}__{digest}"


def _throttle() -> None:
    global _last_request_monotonic
    now = time.monotonic()
    elapsed = now - _last_request_monotonic
    if elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)
    _last_request_monotonic = time.monotonic()


def _append_manifest(url: str, cache_key: str, cache_hit: bool) -> None:
    """Records every fetch() call so cache-hit rate on a second run is
    auditable, and so throttle/retry behavior can be verified after the
    fact rather than taken on faith."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "url": url,
        "cache_key": cache_key,
        "cache_hit": cache_hit,
        "timestamp": time.time(),
    }
    with open(MANIFEST_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def fetch(url: str, *, force_refresh: bool = False) -> bytes:
    """Fetch a URL's raw bytes, with caching and throttling.

    Args:
        url: full URL.
        force_refresh: bypass the cache and re-fetch. Not used in normal
            operation; only for manually invalidating a stale entry.

    Returns:
        Raw response bytes.

    Raises:
        RuntimeError: called before set_user_agent().
        httpx.HTTPError: after MAX_RETRIES failed attempts.
    """
    key = _cache_key(url)
    cache_path = CACHE_DIR / key

    if not force_refresh and cache_path.exists():
        _append_manifest(url, key, cache_hit=True)
        logger.debug("cache hit: %s", url)
        return cache_path.read_bytes()

    user_agent = _require_user_agent()
    backoff = INITIAL_BACKOFF_SECONDS
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        _throttle()
        try:
            resp = httpx.get(
                url,
                headers={"User-Agent": user_agent},
                timeout=30,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning("request failed (attempt %d/%d): %s — %s",
                            attempt, MAX_RETRIES, url, exc)
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 429:
            logger.warning(
                "429 rate-limited (attempt %d/%d), backing off %.1fs: %s",
                attempt, MAX_RETRIES, backoff, url,
            )
            time.sleep(backoff)
            backoff *= 2
            continue

        resp.raise_for_status()

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(resp.content)
        _append_manifest(url, key, cache_hit=False)
        logger.debug("fetched and cached: %s", url)
        return resp.content

    raise httpx.HTTPError(
        f"Failed to fetch {url} after {MAX_RETRIES} attempts"
    ) from last_exc


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print('Usage: python3 src/fetch.py "FirstName LastName netid@illinois.edu"')
        sys.exit(1)

    set_user_agent(sys.argv[1])
    test_url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
    print(f"Testing fetch() against {test_url}")
    data = fetch(test_url)
    print(f"Got {len(data)} bytes. Run again to confirm cache hit.")