# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Jolpica client — the community successor to Ergast (1950 → today).

Ergast shut down at the end of 2024; Jolpica is its drop-in replacement and
carries the only complete open history of the championship. f1verse uses it
for everything the live-timing feeds cannot know: careers, historic circuit
records, standings.
"""
from __future__ import annotations

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


def circuits() -> list:
    """The championship's circuit directory, including retired venues.

    Unlike a race result, this directory grows when a new venue enters the
    calendar. Refresh it on the schedule cadence instead of freezing a
    convenient-but-stale list of "all" circuits in the cache.
    """
    data = get("circuits", limit=1000, ttl=http.TTL_SCHEDULE)
    return data.get("CircuitTable", {}).get("Circuits", [])


def race_rows(path: str, key: str, page: int = 100,
              max_pages: int = 60) -> list:
    """Rows from an endpoint that paginates *inside* a single race.

    ``laps`` and ``pitstops`` return one race whose inner list is the thing
    being paged, so the generic :func:`paged` — which counts races — walks
    forever without making progress. This walks the inner list instead and
    stops on the reported total.
    """
    out, offset = [], 0
    for _ in range(max_pages):
        d = get(path, limit=page, offset=offset)
        races = d["RaceTable"]["Races"]
        rows = races[0].get(key, []) if races else []
        if not rows:
            break
        out += rows
        offset += page
        if offset >= int(d.get("total", 0)):
            break
    return out


def lap_timings(year: int, rnd: int) -> list:
    """Every lap of a race as ``[{"lap": n, "timings": [...]}, ...]``.

    Available from 1996. Each timing carries ``driverId``, ``position`` and
    ``time``, so both the running order and the lap times come from one
    fetch.
    """
    return [{"lap": int(l["number"]), "timings": l["Timings"]}
            for l in race_rows(f"{year}/{rnd}/laps", "Laps")]


def pit_stops(year: int, rnd: int) -> list:
    """Pit stops for a race. Available from 2011."""
    return [{"driver_id": p["driverId"], "lap": int(p["lap"]),
             "stop": int(p["stop"]), "time": p.get("time"),
             "duration_s": float(p["duration"]) if p.get("duration") else None}
            for p in race_rows(f"{year}/{rnd}/pitstops", "PitStops")]
