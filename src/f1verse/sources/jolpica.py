"""Jolpica client — the community successor to Ergast (1950 → today).

Ergast shut down at the end of 2024; Jolpica is its drop-in replacement and
carries the only complete open history of the championship. f1verse uses it
for everything the live-timing feeds cannot know: careers, historic circuit
records, standings.
"""
from .. import http

BASE = "https://api.jolpi.ca/ergast/f1/"


def get(path: str, limit: int = 100, offset: int = 0,
        ttl: float | None = "auto") -> dict:
    """``get('drivers/alonso/results')`` → MRData dict.

    Standings and current-season queries change as a season runs; historic
    results do not. ``ttl='auto'`` picks the right policy from the path.
    """
    if ttl == "auto":
        ttl = (http.TTL_STANDINGS if "standings" in path.lower()
               else http.TTL_FOREVER)
    return http.get_json(f"{BASE}{path}.json",
                         {"limit": limit, "offset": offset}, ttl)["MRData"]


def iter_paged(path: str, table: str, key: str, page: int = 100,
               ttl: float | None = "auto", max_pages: int = 100):
    """Yield rows lazily, with hard and no-progress pagination guards."""
    offset = 0
    for _ in range(max_pages):
        d = get(path, limit=page, offset=offset, ttl=ttl)
        rows = d[table][key]
        if not rows:
            return
        yield from rows
        next_offset = offset + len(rows)
        if next_offset >= int(d["total"]):
            return
        if next_offset <= offset:
            raise RuntimeError(f"pagination made no progress for {path}")
        offset = next_offset
    raise RuntimeError(f"pagination exceeded {max_pages} pages for {path}")


def paged(path: str, table: str, key: str, page: int = 100,
          ttl: float | None = "auto", max_pages: int = 100) -> list:
    """Collect :func:`iter_paged` into a list."""
    return list(iter_paged(path, table, key, page, ttl, max_pages))
