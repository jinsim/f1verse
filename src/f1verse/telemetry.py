"""Car telemetry and track position.

Two high-frequency channels are available per driver and session:

- **car data** — speed, throttle, brake, gear, RPM and DRS, roughly 3.7 Hz.
- **location** — x/y/z track coordinates at similar cadence.

Both are large. A whole session for one driver runs to tens of thousands
of samples, so every function here takes a bounded window (a lap, or an
explicit time range) and the underlying requests are filtered server-side
rather than downloaded whole and trimmed locally.
"""
from datetime import timedelta

from ._json import jsonsafe
from .sources import openf1

# DRS values reported by the timing feed. Values below 8 mean the system is
# not open; 10, 12 and 14 indicate an activated rear wing.
_DRS_OPEN = {10, 12, 14}

# Mini-sector status codes, as carried in the timing feed's per-sector
# ``Segments`` entries. Nothing official documents these; the meanings are
# observable from how they track the on-screen colouring.
SEGMENT_STATUS = {
    0: "not yet run",
    2048: "set",               # completed, nothing special
    2049: "personal best",
    2051: "session best",
    2052: "set",
    2064: "pit in/out lap",
}


def _window(race, driver_number: int, lap: int):
    """Start/end timestamps for one lap, as ISO strings."""
    laps = [l for l in race.laps if l["driver_number"] == driver_number]
    row = next((l for l in laps if l["lap_number"] == lap), None)
    if not row or not row.get("date_start"):
        raise LookupError(f"no start time for driver {driver_number} lap {lap}")
    from datetime import datetime
    start = datetime.fromisoformat(row["date_start"])
    dur = row.get("lap_duration") or 120
    return start.isoformat(), (start + timedelta(seconds=dur + 1)).isoformat()


def lap_telemetry(race, driver: str, lap: int) -> list:
    """Car data for a single lap: speed, throttle, brake, gear, RPM, DRS."""
    num = next((n for n, d in race.drivers.items()
                if d.get("name_acronym") == driver), None)
    if num is None:
        raise LookupError(f"unknown driver {driver!r}")
    lo, hi = _window(race, num, lap)
    rows = openf1.get("car_data", session_key=race.session_key,
                      driver_number=num, **{"date>=": lo, "date<=": hi})
    return jsonsafe([{
        "date": r["date"], "speed": r.get("speed"),
        "throttle": r.get("throttle"), "brake": r.get("brake"),
        "gear": r.get("n_gear"), "rpm": r.get("rpm"),
        "drs_open": r.get("drs") in _DRS_OPEN,
    } for r in rows])


def lap_trace(race, driver: str, lap: int) -> list:
    """Track coordinates for a single lap — the path a car actually took."""
    num = next((n for n, d in race.drivers.items()
                if d.get("name_acronym") == driver), None)
    if num is None:
        raise LookupError(f"unknown driver {driver!r}")
    lo, hi = _window(race, num, lap)
    rows = openf1.get("location", session_key=race.session_key,
                      driver_number=num, **{"date>=": lo, "date<=": hi})
    return jsonsafe([{"date": r["date"], "x": r.get("x"),
                      "y": r.get("y"), "z": r.get("z")} for r in rows])


def top_speeds(race, threshold: int = 300) -> dict:
    """Highest speed recorded per driver above *threshold* km/h.

    Filtered server-side, so this is one small request per driver rather
    than a full-session download.
    """
    out = {}
    for num, d in race.drivers.items():
        rows = openf1.get("car_data", session_key=race.session_key,
                          driver_number=num, **{"speed>=": threshold})
        if rows:
            best = max(rows, key=lambda r: r.get("speed") or 0)
            out[d.get("name_acronym") or str(num)] = {
                "speed": best["speed"], "date": best["date"],
                "gear": best.get("n_gear"), "drs_open": best.get("drs") in _DRS_OPEN,
            }
    return jsonsafe(dict(sorted(out.items(),
                                key=lambda kv: -kv[1]["speed"])))
