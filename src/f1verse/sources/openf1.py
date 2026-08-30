"""Thin OpenF1 REST client (https://openf1.org) — coverage from 2023 season."""
from .. import http

BASE = "https://api.openf1.org/v1/"

# Schedules move (rounds get cancelled mid-season); session data does not.
_MUTABLE = {"sessions": http.TTL_SCHEDULE, "meetings": http.TTL_SCHEDULE}


def get(endpoint: str, ttl: float | None = "auto", **params) -> list:
    """Fetch an OpenF1 endpoint.

    ``ttl='auto'`` (default) caches schedule endpoints for a few hours and
    everything else forever, because completed-session rows never change.
    """
    if ttl == "auto":
        ttl = _MUTABLE.get(endpoint, http.TTL_FOREVER)
    return http.get_json(BASE + endpoint, params, ttl)


def resolve_race(year: int, rnd: int) -> dict:
    """(year, round) → race session dict. Rounds count real GP meetings only."""
    if year < 2023:
        raise ValueError("native race loading is available from the 2023 season")
    meetings = sorted(get("meetings", year=year), key=lambda m: m["date_start"])
    gps = [m for m in meetings
           if "test" not in m["meeting_name"].lower()
           and not m.get("is_cancelled")]
    if not 1 <= rnd <= len(gps):
        raise ValueError(f"round {rnd} out of range (1..{len(gps)})")
    m = gps[rnd - 1]
    race = get("sessions", meeting_key=m["meeting_key"], session_name="Race")
    if not race:
        raise LookupError(f"no Race session for {m['meeting_name']}")
    s = race[0]
    s["meeting"] = m
    return s
