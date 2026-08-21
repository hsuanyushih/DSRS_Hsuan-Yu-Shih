"""
fetch.py -- SEC fetch helper with caching, rate-limiting, and a proper User-Agent.

All outbound network requests in Chapter 1 (CIK lookup table, submissions API,
archive directory, XML files) should go through this module's fetch() function.
Reasons:
  1. SEC requires every request to carry a User-Agent; omitting it fails the whole
     chapter outright.
  2. SEC caps requests at 10/second; throttling is centralized here instead of being
     duplicated at every call site.
  3. The pipeline must run twice with the second run noticeably faster -- the caching
     logic lives here so every caller automatically gets cache-and-resume behavior.

Usage:
    from fetch import fetch
    raw_bytes = fetch("https://data.sec.gov/submissions/CIK0001037389.json")
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config: fill in your own name and illinois.edu email; SEC requires this format.
# Do not leave it blank or use someone else's info -- a missing or malformed
# User-Agent fails Chapter 1 outright, the one "zero tolerance" condition in the spec.
# ---------------------------------------------------------------------------
USER_AGENT = "Hsuan-Yu Shih hsuanyu5@illinois.edu"  # TODO: replace with your real info

CACHE_DIR = Path("output/.cache")
MANIFEST_PATH = CACHE_DIR / "manifest.jsonl"

# SEC's cap is 10 requests/second; we deliberately target 8/second here to leave a
# safety margin, so the program's own execution latency doesn't push the actual rate
# right up against the limit.
MIN_INTERVAL_SECONDS = 1.0 / 8.0

# Backoff seconds when rate-limited (429); exponential backoff, gives up after a max
# number of retries.
INITIAL_BACKOFF_SECONDS = 2.0
MAX_RETRIES = 5

_last_request_monotonic = 0.0


def _cache_key(url: str) -> str:
    """
    Turn a URL into a filename that is safe and easy to recognize by eye.
    Prefers the last segments of the URL path as a readable prefix, then appends a
    hash to avoid collisions.
    """
    parsed = urlparse(url)
    readable = parsed.path.strip("/").replace("/", "_") or "root"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return f"{readable}__{digest}"


def _throttle() -> None:
    """Ensure at least MIN_INTERVAL_SECONDS between two consecutive actual requests."""
    global _last_request_monotonic
    now = time.monotonic()
    elapsed = now - _last_request_monotonic
    if elapsed < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - elapsed)
    _last_request_monotonic = time.monotonic()


def _append_manifest(url: str, cache_key: str, cache_hit: bool) -> None:
    """
    Record the result of every fetch, used as evidence that:
      (a) the second pipeline run produces a large number of cache_hit=true entries
      (b) you actually exercised the throttle/retry logic, not hammered the API
    This manifest can be opened directly during the Chapter 5 recording, or cited
    as evidence in submission/ASSUMPTIONS.md.
    """
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
    """
    Fetch the raw bytes for a URL, with caching and throttling.

    Args:
        url: the full URL.
        force_refresh: if True, ignore any existing cache and force a fresh network
                       request. Not for normal use -- only turn this on manually when
                       you suspect the cache is stale.

    Returns:
        the raw bytes of the response for this URL.

    Raises:
        requests.HTTPError: if it still fails after MAX_RETRIES attempts.
    """
    key = _cache_key(url)
    cache_path = CACHE_DIR / key

    if not force_refresh and cache_path.exists():
        _append_manifest(url, key, cache_hit=True)
        logger.debug("cache hit: %s", url)
        return cache_path.read_bytes()

    backoff = INITIAL_BACKOFF_SECONDS
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        _throttle()
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("request failed (attempt %d/%d): %s — %s",
                            attempt, MAX_RETRIES, url, exc)
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 429:
            # rate-limited: back off instead of retrying immediately, so a temporary
            # throttle doesn't turn into a permanent block.
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

    raise requests.HTTPError(
        f"Failed to fetch {url} after {MAX_RETRIES} attempts"
    ) from last_exc


if __name__ == "__main__":
    # quick self-test: fetch a small file to confirm the User-Agent/cache logic works.
    logging.basicConfig(level=logging.INFO)
    test_url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
    print(f"Testing fetch() against {test_url}")
    data = fetch(test_url)
    print(f"Got {len(data)} bytes. Run again to confirm cache hit.")