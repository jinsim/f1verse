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


def paged(path: str, table: str, key: str, page: int = 100,
          ttl: float | None = "auto") -> list:
    """Follow Jolpica pagination until everything is collected."""
    out, offset = [], 0
    while True:
        d = get(path, limit=page, offset=offset, ttl=ttl)
        rows = d[table][key]
        out += rows
        offset += page
        if offset >= int(d["total"]) or not rows:
            return out
