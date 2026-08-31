# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Additional live-timing feeds.

The official archive publishes a number of topics that are rarely
surfaced. Three of them carry information worth having:

- ``ChampionshipPrediction`` — per-lap "if the race ended now" projection.
- ``TeamRadio`` — timestamped team-radio clip paths (URLs only, no media).
- ``TimingStats`` — personal bests and speed-trap figures.

Every function accepts an :class:`f1verse.Race` — or anything exposing
``.api_path``.
"""
import copy

from ._json import jsonsafe
from .sources.livetiming import BASE, deepmerge, fetch_stream


def _path(session) -> str:
    p = getattr(session, "api_path", None)
    if not p:
        raise TypeError("expected an object with an .api_path (f1verse.Race)")
    return p


def championship_prediction(session) -> dict:
    """Live championship projection through the race.

    Returns ``{"series", "final", "leader_changes"}`` where
    ``leader_changes`` are the moments the *projected champion* changed —
    the moments no broadcast graphic shows.
    """
    series, state = [], {}
    for t, patch in fetch_stream(_path(session), "ChampionshipPrediction.jsonStream"):
        state = deepmerge(state, patch)
        if state.get("Drivers"):
            series.append({"t": t, "state": copy.deepcopy(state)})
    changes, prev = [], None
    for snap in series:
        drivers = snap["state"].get("Drivers", {})
        leader = min((d for d in drivers.values() if d.get("PredictedPosition")),
                     key=lambda d: d["PredictedPosition"], default=None)
        num = leader and leader.get("RacingNumber")
        if num and num != prev:
            if prev is not None:
                changes.append({"t": snap["t"], "to": num, "from": prev})
            prev = num
    return jsonsafe({"series": series,
                     "final": series[-1]["state"] if series else {},
                     "leader_changes": changes})


def team_radio(session) -> list:
    """Timestamped team-radio clips: URLs only, nothing downloaded."""
    clips, path = [], _path(session)
    for t, patch in fetch_stream(path, "TeamRadio.jsonStream"):
        caps = patch.get("Captures")
        items = caps.values() if isinstance(caps, dict) else (caps or [])
        for c in items:
            if isinstance(c, dict) and c.get("Path"):
                clips.append({"t": t, "utc": c.get("Utc"),
                              "driver_number": c.get("RacingNumber"),
                              "url": BASE + path + c["Path"]})
    return jsonsafe(clips)


def timing_stats(session) -> dict:
    """Final personal bests / best sectors / speed-trap figures per driver."""
    state = {}
    for _, patch in fetch_stream(_path(session), "TimingStats.jsonStream"):
        state = deepmerge(state, patch)
    return jsonsafe(state.get("Lines", {}))


def overtake_signals(session) -> list:
    """Moments the timing feed itself flags as a pass in progress.

    ``DriverRaceInfo`` carries an ``OvertakeState`` per car, and it is
    almost always unchanged — a race of nearly twenty thousand records
    turns over about a hundred times. That sparsity is the point: the
    transitions are a free index of the moments worth looking at, published
    by the same feed that times the race, and independent of any passing
    logic of our own.

    Returns one entry per transition, with the session time, the car, and
    the state either side. Read it as "something happened here", not as a
    completed pass — confirm against the running order before calling it
    an overtake.
    """
    seen: dict = {}
    out = []
    for t, patch in fetch_stream(_path(session), "DriverRaceInfo.jsonStream"):
        for num, line in (patch or {}).items():
            if not isinstance(line, dict) or "OvertakeState" not in line:
                continue
            state = line["OvertakeState"]
            was = seen.get(num)
            if was is not None and was != state:
                out.append({"t": round(t, 3), "driver_number": num,
                            "abbr": session.abbr(int(num))
                            if str(num).isdigit() else num,
                            "from_state": was, "to_state": state,
                            "gap": line.get("Gap"),
                            "interval": line.get("Interval")})
            seen[num] = state
    return jsonsafe(out)


def overtake_hotspots(session, window_s: float = 30.0) -> list:
    """Where the passing signals cluster, as candidate highlight windows.

    Transitions are grouped into ``window_s`` buckets; the busiest buckets
    are the stretches of race with the most cars changing state at once.
    Useful as an editing index — start with the densest window and work
    down.
    """
    sig = overtake_signals(session)
    if not sig:
        return []
    buckets: dict = {}
    for s in sig:
        b = int(s["t"] // window_s)
        buckets.setdefault(b, []).append(s)
    rows = [{"from_s": round(b * window_s, 1),
             "to_s": round((b + 1) * window_s, 1),
             "signals": len(v),
             "drivers": sorted({s["abbr"] for s in v})}
            for b, v in sorted(buckets.items())]
    return jsonsafe(sorted(rows, key=lambda r: -r["signals"]))
