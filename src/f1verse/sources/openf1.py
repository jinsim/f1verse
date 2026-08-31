# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Thin OpenF1 REST client (https://openf1.org) — coverage from 2023 season."""
from __future__ import annotations

from .. import http

BASE = "https://api.openf1.org/v1/"

# Schedules move (rounds get cancelled mid-season); session data does not.
_MUTABLE = {"sessions": http.TTL_SCHEDULE, "meetings": http.TTL_SCHEDULE}

# Endpoints a post-session decision can rewrite. The chequered flag ends
# the running, not the classification: scrutineering disqualifications,
# time penalties and amended race-control logs land hours later and change
# these rows in place. Caching them forever hides the correction — so the
# loader keeps them on a short TTL until the session is final, then lets
# them settle. See ``race.Race._load``.
REVISABLE = frozenset({"session_result", "race_control", "starting_grid",
                       "stints", "pit"})


def get(endpoint: str, ttl: float | None = "auto", **params) -> list:
    """Fetch an OpenF1 endpoint.

    ``ttl='auto'`` (default) caches schedule endpoints for a few hours and
    everything else forever, because completed-session rows never change.
    Endpoints in :data:`REVISABLE` are the exception; callers that know a
    session's age pass an explicit ``ttl``.
    """
    if ttl == "auto":
        ttl = _MUTABLE.get(endpoint, http.TTL_FOREVER)
    return http.get_json(BASE + endpoint, params, ttl)


def meta(endpoint: str, **params) -> dict:
    """Cache provenance for the same request :func:`get` would make."""
    return http.entry_meta(BASE + endpoint, params)


def resolve_race(year: int, rnd: int) -> dict:
    """(year, round) → race session dict. Rounds count real GP meetings only."""
    return resolve_session(year, rnd, "Race")


def resolve_session(year: int, rnd: int, session_name: str = "Race") -> dict:
    """(year, round, session) → session dict with its meeting attached.

    Rounds count real GP meetings only, so cancelled rounds do not shift
    the numbering. *session_name* is matched as OpenF1 spells it —
    ``Race``, ``Qualifying``, ``Sprint``, ``Sprint Qualifying``,
    ``Practice 1``…
    """
    if year < 2023:
        raise ValueError("native session loading is available from the 2023 season")
    meetings = sorted(get("meetings", year=year), key=lambda m: m["date_start"])
    gps = [m for m in meetings
           if "test" not in m["meeting_name"].lower()
           and not m.get("is_cancelled")]
    if not 1 <= rnd <= len(gps):
        raise ValueError(f"round {rnd} out of range (1..{len(gps)})")
    m = gps[rnd - 1]
    rows = get("sessions", meeting_key=m["meeting_key"])
    hit = [s for s in rows if s["session_name"] == session_name]
    if not hit:
        have = ", ".join(sorted(s["session_name"] for s in rows))
        raise LookupError(
            f"no {session_name!r} session for {m['meeting_name']} — has: {have}")
    s = dict(hit[0])
    s["meeting"] = m
    return s
