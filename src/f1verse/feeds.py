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
