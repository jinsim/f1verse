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

**Revision journal**

Caching by mutability is a claim about the world: *this will never
change*. Where the claim is wrong, the cache makes the error invisible —
a stewards' decision rewrites a classification and every later run still
serves the copy taken before it. So whenever a re-fetch returns a body
that differs from the cached one, the previous body is kept and the
change is appended to ``_revisions.jsonl``.

This is deliberately **not** a vintage archive. It records only the
changes this installation actually observed; it cannot reconstruct a
value nobody here ever fetched. :func:`revisions` reads it back.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from ._version import __version__

_UA = f"f1verse/{__version__} (+https://github.com/jinsim/f1verse)"
_cache_dir = Path.home() / ".cache" / "f1verse"
_last_request = 0.0

# Conventional TTLs, exported so callers do not invent their own numbers.
HOUR = 3600
DAY = 86400
TTL_SCHEDULE = 6 * HOUR     # sessions, meetings — dates and cancellations move
TTL_STANDINGS = HOUR        # championship tables during a season
TTL_LIVE = 60               # anything from a session in progress
TTL_PROVISIONAL = 15 * 60   # classification the stewards can still rewrite
TTL_FOREVER = None          # completed-session data
_MAX_RETRY_AFTER = 120.0

# Journal and kept vintages live inside the cache directory but are not
# cache entries: they survive clear_cache and are excluded from cache_info.
JOURNAL = "_revisions.jsonl"
VINTAGES = "_vintages"
_VINTAGE_MAX_BYTES = 1 << 20   # keep the superseded body when it is small

# Hosts that publish a request budget get it honoured here, at the layer
# every request passes through, rather than trusted to each call site.
# Exhausting a budget raises rather than silently sleeping for most of an
# hour — the error names the wait, so a caller can decide.
_HOURLY_BUDGET = {"api.jolpi.ca": 200}
_DEFAULT_HOURLY_BUDGET = 500
_request_log: dict = {}


class BudgetExhausted(RuntimeError):
    """The hourly request budget for a host is spent."""


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _retry_delay(value: str | None, attempt: int) -> float:
    """Parse both Retry-After forms, with bounded exponential fallback."""
    if value:
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = parsedate_to_datetime(value).timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                delay = None
        if delay is not None:
            return min(max(delay, 0.0), _MAX_RETRY_AFTER)
    base = min(2 ** attempt, 30)
    return base + random.uniform(0, base * 0.25)


def enable_cache(path) -> None:
    """Override the cache directory (default ``~/.cache/f1verse``)."""
    global _cache_dir
    _cache_dir = Path(path)


def cache_info() -> dict:
    """Entry count and total size — for operators, not for the library."""
    if not _cache_dir.exists():
        return {"path": str(_cache_dir), "entries": 0, "bytes": 0,
                "revisions": 0}
    files = [f for f in _cache_dir.iterdir()
             if f.is_file() and f.name != JOURNAL]
    return {"path": str(_cache_dir), "entries": len(files),
            "bytes": sum(f.stat().st_size for f in files),
            "revisions": sum(1 for _ in _journal_lines())}


def clear_cache(older_than: float | None = None) -> int:
    """Delete cache entries; with *older_than* seconds, only stale ones.

    The revision journal and the vintages it points at are never deleted:
    they are the record of what changed, not a copy of what is current.
    """
    if not _cache_dir.exists():
        return 0
    now, removed = time.time(), 0
    for f in _cache_dir.iterdir():
        if (f.is_file() and f.name != JOURNAL
                and (older_than is None
                     or now - f.stat().st_mtime > older_than)):
            f.unlink()
            removed += 1
    return removed


def _spend(host: str) -> None:
    limit = _HOURLY_BUDGET.get(host, _DEFAULT_HOURLY_BUDGET)
    log = _request_log.setdefault(host, deque())
    now = time.monotonic()
    while log and now - log[0] > 3600:
        log.popleft()
    if len(log) >= limit:
        retry_in = int(3600 - (now - log[0])) + 1
        raise BudgetExhausted(
            f"{host}: {limit} requests in the last hour; "
            f"a slot frees in {retry_in}s")
    log.append(now)


def _fetch(url: str) -> str:
    global _last_request
    _spend(urllib.parse.urlsplit(url).hostname or "")
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
            time.sleep(_retry_delay(e.headers.get("Retry-After"), attempt))
    _last_request = time.monotonic()
    return raw.decode("utf-8-sig")  # livetiming serves BOM-prefixed JSON


def build_url(url: str, params: dict | None = None) -> str:
    """Final request URL — the cache key, and what the journal records."""
    if not params:
        return url
    # These APIs express ranges as ``date>=value``, where the operator
    # sits between name and value rather than after an "=". urlencode
    # would emit ``date>===value``, so such pairs are built by hand.
    parts = []
    for k, v in params.items():
        if k.endswith((">=", "<=", ">", "<")):
            op = k[-2:] if k.endswith(("=",)) and k[-2] in "><" else k[-1]
            name = k[:-len(op)]
            parts.append(f"{name}{op}{urllib.parse.quote(str(v), safe=':+.')}")
        else:
            parts.append(urllib.parse.urlencode({k: v}))
    return url + "?" + "&".join(parts)


def _entry(url: str) -> Path:
    return _cache_dir / hashlib.sha256(url.encode()).hexdigest()[:24]


# -- revision journal -------------------------------------------------------

def _row_delta(previous: str, current: str) -> dict:
    """Row-level shape of a change, when both bodies are JSON row lists."""
    try:
        a, b = json.loads(previous), json.loads(current)
    except ValueError:
        return {}
    if not (isinstance(a, list) and isinstance(b, list)):
        return {}
    def rows(x):
        return {json.dumps(r, sort_keys=True) for r in x if isinstance(r, dict)}
    sa, sb = rows(a), rows(b)
    return {"rows_before": len(a), "rows_after": len(b),
            "rows_added": len(sb - sa), "rows_removed": len(sa - sb)}


def _record(url: str, entry: Path, previous: str, current: str) -> None:
    now = time.time()
    rec = {"observed_at": _iso(now),
           "url": url,
           "previous_seen_at": _iso(entry.stat().st_mtime),
           "previous_sha256": _sha(previous),
           "current_sha256": _sha(current)}
    rec.update(_row_delta(previous, current))
    if len(previous.encode()) <= _VINTAGE_MAX_BYTES:
        d = _cache_dir / VINTAGES / entry.name
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{int(now)}-{rec['previous_sha256'][:12]}.json"
        p.write_text(previous)
        rec["previous_body"] = str(p.relative_to(_cache_dir))
    with (_cache_dir / JOURNAL).open("a") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")


def _journal_lines():
    f = _cache_dir / JOURNAL
    if not f.exists():
        return
    for line in f.read_text().splitlines():
        if line.strip():
            try:
                yield json.loads(line)
            except ValueError:
                continue


def revisions(url_contains: str | None = None, *,
              since: str | None = None) -> list:
    """Changes this installation observed, oldest first.

    Each record carries the URL, when the superseded copy was taken, when
    the change was seen, both hashes, a row-count delta, and — when it was
    small enough to keep — a path to the superseded body (:func:`vintage`).
    """
    out = []
    for rec in _journal_lines():
        if url_contains and url_contains not in rec.get("url", ""):
            continue
        if since and rec.get("observed_at", "") < since:
            continue
        out.append(rec)
    return out


def vintage(record: dict):
    """The superseded body of a revision record, or ``None`` if not kept."""
    rel = record.get("previous_body")
    if not rel:
        return None
    p = _cache_dir / rel
    return json.loads(p.read_text()) if p.exists() else None


def entry_meta(url: str, params: dict | None = None) -> dict:
    """Cache provenance for one request — is it cached, and how old."""
    u = build_url(url, params)
    f = _entry(u)
    if not f.exists():
        return {"url": u, "cached": False,
                "fetched_at": None, "age_seconds": None, "sha256": None}
    st = f.stat()
    return {"url": u, "cached": True,
            "fetched_at": _iso(st.st_mtime),
            "age_seconds": round(time.time() - st.st_mtime, 1),
            "sha256": _sha(f.read_text())}


# -- request ----------------------------------------------------------------

def get_text(url: str, params: dict | None = None,
             ttl: float | None = None) -> str:
    url = build_url(url, params)
    f = _entry(url)
    fresh = f.exists() and (ttl is None
                            or time.time() - f.stat().st_mtime < ttl)
    if fresh:
        return f.read_text()
    previous = f.read_text() if f.exists() else None
    try:
        text = _fetch(url)
    except Exception:
        if previous is not None:
            return previous   # stale beats nothing
        raise
    _cache_dir.mkdir(parents=True, exist_ok=True)
    if previous is not None and previous != text:
        _record(url, f, previous, text)
    f.write_text(text)
    return text


def get_json(url: str, params: dict | None = None,
             ttl: float | None = None):
    return json.loads(get_text(url, params, ttl))
