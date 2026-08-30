"""Cached HTTP layer — standard library only, zero dependencies.

**Caching policy**

Completed sessions never change, so their data is cached forever. Anything
that can still move — schedules, standings, an in-progress season — must
expire, or a cached calendar will hide a cancelled round for the rest of
the year. Callers declare intent with ``ttl``:

- ``ttl=None`` (default): immutable. Cache forever.
- ``ttl=seconds``: re-fetch once the entry is older than that.
- ``ttl=0``: always fetch (still writes the entry, so a later failure can
  fall back to it).

If a refresh fails but a stale entry exists, the stale copy is served
rather than raising — a schedule from an hour ago beats no schedule.
"""
import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_UA = "f1verse (+https://github.com/jinsim/f1verse)"
_cache_dir = Path.home() / ".cache" / "f1verse"
_last_request = 0.0

# Conventional TTLs, exported so callers do not invent their own numbers.
HOUR = 3600
DAY = 86400
TTL_SCHEDULE = 6 * HOUR     # sessions, meetings — dates and cancellations move
TTL_STANDINGS = HOUR        # championship tables during a season
TTL_LIVE = 60               # anything from a session in progress
TTL_FOREVER = None          # completed-session data


def enable_cache(path) -> None:
    """Override the cache directory (default ``~/.cache/f1verse``)."""
    global _cache_dir
    _cache_dir = Path(path)


def cache_info() -> dict:
    """Entry count and total size — for operators, not for the library."""
    if not _cache_dir.exists():
        return {"path": str(_cache_dir), "entries": 0, "bytes": 0}
    files = [f for f in _cache_dir.iterdir() if f.is_file()]
    return {"path": str(_cache_dir), "entries": len(files),
            "bytes": sum(f.stat().st_size for f in files)}


def clear_cache(older_than: float | None = None) -> int:
    """Delete cache entries; with *older_than* seconds, only stale ones."""
    if not _cache_dir.exists():
        return 0
    now, removed = time.time(), 0
    for f in _cache_dir.iterdir():
        if f.is_file() and (older_than is None
                            or now - f.stat().st_mtime > older_than):
            f.unlink()
            removed += 1
    return removed


def _fetch(url: str) -> str:
    global _last_request
    wait = 0.5 - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept-Encoding": "gzip"})
    # Public F1 APIs rate-limit bulk season queries; back off and retry
    # rather than failing a long-running aggregation halfway through.
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            break
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504) or attempt == 5:
                raise
            retry_after = e.headers.get("Retry-After")
            delay = (float(retry_after) if retry_after and retry_after.isdigit()
                     else min(2 ** attempt, 30))
            time.sleep(delay)
    _last_request = time.monotonic()
    return raw.decode("utf-8-sig")  # livetiming serves BOM-prefixed JSON


def get_text(url: str, params: dict | None = None,
             ttl: float | None = None) -> str:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    f = _cache_dir / hashlib.sha256(url.encode()).hexdigest()[:24]
    fresh = f.exists() and (ttl is None
                            or time.time() - f.stat().st_mtime < ttl)
    if fresh:
        return f.read_text()
    try:
        text = _fetch(url)
    except Exception:
        if f.exists():
            return f.read_text()   # stale beats nothing
        raise
    _cache_dir.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    return text


def get_json(url: str, params: dict | None = None,
             ttl: float | None = None):
    return json.loads(get_text(url, params, ttl))
