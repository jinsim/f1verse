# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Circuit profiles — geometry, layout facts and historic record in one call.

Answers the questions a race preview asks: what does this track look like,
how many corners, how costly is a pit stop here, who wins here, and does
pole convert?
"""
from __future__ import annotations

import math

from ._json import jsonsafe
from .history import circuit_history
from .sources import jolpica, multiviewer, openf1

# Jolpica circuit ids differ from OpenF1 short names for a handful of tracks.
_JOLPICA_ID = {
    "Zandvoort": "zandvoort", "Monza": "monza", "Spa-Francorchamps": "spa",
    "Silverstone": "silverstone", "Monaco": "monaco", "Suzuka": "suzuka",
    "Interlagos": "interlagos", "Yas Marina Circuit": "yas_marina",
    "Hungaroring": "hungaroring", "Red Bull Ring": "red_bull_ring",
    "Catalunya": "catalunya", "Baku": "baku", "Jeddah": "jeddah",
    "Sakhir": "bahrain", "Melbourne": "albert_park", "Shanghai": "shanghai",
    "Miami": "miami", "Montreal": "villeneuve", "Marina Bay": "marina_bay",
    "Austin": "americas", "Mexico City": "rodriguez", "Las Vegas": "vegas",
    "Losail": "losail", "Imola": "imola", "Madring": "madring",
}


def _number(value):
    """A finite float, or ``None`` for a malformed coordinate."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _trace(raw: dict) -> list:
    """Paired finite x/y points, preserving the feed's driving order."""
    xs, ys = raw.get("x") or [], raw.get("y") or []
    points = []
    for x, y in zip(xs, ys):
        x, y = _number(x), _number(y)
        if x is not None and y is not None:
            points.append((x, y))
    return points


def _walk(points: list) -> tuple:
    """Cumulative distance around a closed trace, in source coordinates."""
    if len(points) < 2:
        return [], 0.0
    cumulative, total = [0.0], 0.0
    for a, b in zip(points, points[1:] + points[:1]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
        cumulative.append(total)
    return cumulative, total


def _winding(points: list) -> tuple:
    """Signed area and winding in the source's coordinate plane.

    This intentionally says *trace* winding, not a real-world left/right
    turn direction. A map provider may flip its y axis, and guessing would
    make a precise-looking but false driving claim.
    """
    twice_area = sum(a[0] * b[1] - b[0] * a[1]
                     for a, b in zip(points, points[1:] + points[:1]))
    if math.isclose(twice_area, 0.0, abs_tol=1e-9):
        return 0.0, "indeterminate"
    return twice_area / 2, "counterclockwise" if twice_area > 0 else "clockwise"


def _nearest_progress(point: dict, points: list, cumulative: list,
                      total: float) -> float | None:
    """Lap progress for a labelled coordinate, without trusting its length tag."""
    x, y = _number(point.get("x")), _number(point.get("y"))
    if x is None or y is None or not points or not total:
        return None
    index = min(range(len(points)),
                key=lambda i: (points[i][0] - x) ** 2 + (points[i][1] - y) ** 2)
    return 100 * cumulative[index] / total


def _deflection(points: list, index: int) -> float | None:
    """Local change of heading at a labelled point, in degrees.

    A modest window filters the tiny bends created by digitised polylines.
    It is a comparable shape measure, not a claim about an FIA corner's
    official radius or speed.
    """
    count = len(points)
    if count < 8:
        return None
    span = max(2, count // 80)  # roughly a 2.5% lap-wide heading window
    before, here, after = points[(index - span) % count], points[index], points[(index + span) % count]
    incoming = (here[0] - before[0], here[1] - before[1])
    outgoing = (after[0] - here[0], after[1] - here[1])
    if not (math.hypot(*incoming) and math.hypot(*outgoing)):
        return None
    cross = incoming[0] * outgoing[1] - incoming[1] * outgoing[0]
    dot = incoming[0] * outgoing[0] + incoming[1] * outgoing[1]
    return math.degrees(math.atan2(cross, dot))


def _nearest_index(point: dict, points: list) -> int | None:
    x, y = _number(point.get("x")), _number(point.get("y"))
    if x is None or y is None or not points:
        return None
    return min(range(len(points)),
               key=lambda i: (points[i][0] - x) ** 2 + (points[i][1] - y) ** 2)


def layout_diagnostics(raw: dict) -> dict:
    """Describe a circuit trace without inventing physical measurements.

    ``raw`` is any ordered x/y trace, optionally with the corner, marshal and
    mini-sector markers used by public timing-map feeds. The result preserves
    source-coordinate measurements under explicit names and derives only
    unit-free quantities (lap percentage, aspect ratio and local heading
    deflection). It therefore remains useful when a map supplies no surveyed
    track length, elevation series or DRS zoning.
    """
    points = _trace(raw)
    cumulative, total = _walk(points)
    if len(points) < 3 or not total:
        return jsonsafe({
            "available": False,
            "reason": "fewer than three finite trace points",
            "point_count": len(points),
        })

    xs, ys = [p[0] for p in points], [p[1] for p in points]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    area, winding = _winding(points)
    bounds_area = span_x * span_y

    corner_rows = []
    for corner in raw.get("corners") or []:
        if not isinstance(corner, dict):
            continue
        index = _nearest_index(corner.get("trackPosition") or {}, points)
        progress = (100 * cumulative[index] / total) if index is not None else None
        turn = _deflection(points, index) if index is not None else None
        corner_rows.append({
            "number": corner.get("number"),
            "source_distance": corner.get("length"),
            "progress_pct": round(progress, 3) if progress is not None else None,
            "local_deflection_deg": round(turn, 3) if turn is not None else None,
        })
    positioned = sorted((r for r in corner_rows if r["progress_pct"] is not None),
                        key=lambda r: r["progress_pct"])
    for i, row in enumerate(positioned):
        previous = positioned[i - 1]["progress_pct"]
        run = row["progress_pct"] - previous
        row["run_from_previous_pct"] = round(run if run > 0 else run + 100, 3)

    markers = set()
    for marker in raw.get("miniSectorsIndexes") or []:
        try:
            marker = int(marker)
        except (TypeError, ValueError):
            continue
        if 0 < marker < len(points):
            markers.add(marker)
    markers = sorted(markers)
    mini_sectors, start = [], 0
    for end in markers:
        mini_sectors.append({"from_point": start, "to_point": end,
                              "lap_pct": round(100 * (cumulative[end] - cumulative[start]) / total, 3)})
        start = end
    if start < len(points) - 1:
        mini_sectors.append({"from_point": start, "to_point": len(points) - 1,
                              "lap_pct": round(100 * (total - cumulative[start]) / total, 3)})

    marshal = []
    for sector in raw.get("marshalSectors") or []:
        if not isinstance(sector, dict):
            continue
        progress = _nearest_progress(sector.get("trackPosition") or {}, points,
                                     cumulative, total)
        marshal.append({"number": sector.get("number"),
                        "progress_pct": round(progress, 3) if progress is not None else None})

    return jsonsafe({
        "available": True,
        "point_count": len(points),
        "coordinate_path_length": round(total, 3),
        "coordinate_units": "map-source units (not surveyed metres)",
        "bounds": {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)],
                   "aspect_ratio": round(span_x / span_y, 4) if span_y else None,
                   "trace_to_bounds_fill": round(abs(area) / bounds_area, 4)
                   if bounds_area else None},
        "trace_winding": winding,
        "corners": corner_rows,
        "mini_sectors": mini_sectors,
        "marshal_sector_markers": marshal,
        # None of these three are in a map feed, but none of them are lost:
        # the cars record all of them every time they run, so each names
        # the survey that measures it rather than reporting a dead end.
        "coverage": {
            "elevation": {
                "available": False,
                "reason": "the geometry source supplies no altitude series",
                "measurable_by": "survey.elevation — the position feed's "
                                 "height channel, off a clean lap"},
            "drs_zones": {
                "available": False,
                "reason": "the geometry source supplies no DRS-zone geometry",
                "measurable_by": "survey.drs_zones — where cars are recorded "
                                 "running an open wing"},
            "track_width": {
                "available": False,
                "reason": "the geometry source supplies a centre trace, not boundaries",
                "measurable_by": "survey.driven_corridor — the spread of "
                                 "lines the field drove, a lower bound"},
        },
    })


def directory() -> dict:
    """Every Formula 1 venue in the historical results directory.

    This is deliberately a directory, not a hand-maintained claims database:
    it gives a stable circuit id, name and geographic location for every
    venue recorded by the championship. Use that id with
    :func:`history.circuit_history` for results-led detail. Geometry is
    separate because a present-day trace must never be silently assigned to
    an older layout of the same venue.
    """
    rows = []
    for row in jolpica.circuits():
        location = row.get("Location") or {}
        rows.append({
            "id": row.get("circuitId"),
            "name": row.get("circuitName"),
            "location": {
                "locality": location.get("locality"),
                "country": location.get("country"),
                "latitude": _number(location.get("lat")),
                "longitude": _number(location.get("long")),
            },
        })
    rows.sort(key=lambda row: ((row["location"]["country"] or ""),
                               (row["name"] or "")))
    return jsonsafe({
        "circuits": rows,
        "coverage": {
            "history": "Formula 1 venues recorded in Jolpica's 1950-present results",
            "geometry": "provided separately and only when tied to a specific season/layout",
        },
        "source": "Jolpica circuit directory",
    })


def profile(year: int, rnd: int, history: bool = True,
            measure: bool = False) -> dict:
    """Circuit profile for a given round.

    With ``measure`` the profile also carries what only the cars know:
    the height profile, the DRS zones and the width of road the field
    used, surveyed from that weekend's own telemetry. It costs a handful
    of extra requests, so it is off by default and asked for when wanted.
    """
    s = openf1.resolve_race(year, rnd)
    m = s["meeting"]
    geo = multiviewer.circuit(m["circuit_key"], year)
    corners = geo.get("corners", [])
    diagnosis = layout_diagnostics(geo)
    by_number = {c.get("number"): c for c in diagnosis.get("corners", [])}
    out = {
        "name": geo.get("circuitName") or m["circuit_short_name"],
        "official_name": m.get("meeting_official_name"),
        "country": m.get("country_name"),
        "location": m.get("location"),
        "type": m.get("circuit_type"),
        "utc_offset": m.get("gmt_offset"),
        "corners": len(corners),
        "corner_detail": [{"number": c.get("number"), "angle": c.get("angle"),
                           "distance": c.get("length"),
                           **{k: v for k, v in by_number.get(c.get("number"), {}).items()
                              if k not in {"number", "source_distance"}}}
                          for c in corners],
        "marshal_sectors": len(geo.get("marshalSectors", [])),
        # seconds lost in the pit lane, split by track state — the number an
        # undercut calculation needs, and the reason a VSC stop is "cheap"
        "pit_loss_s": {k: float(v) for k, v in
                       (geo.get("pitLoss") or {}).items()},
        "outline": {"x": geo.get("x", []), "y": geo.get("y", []),
                    "rotation": geo.get("rotation")},
        "reference_lap": (lambda c: {
            "time_s": c.get("lapTime"), "session": c.get("session"),
            "driver_number": c.get("driverNumber")} if c else None)(
                geo.get("candidateLap")),
        "layout": diagnosis,
        "sources": {
            "geometry": "MultiViewer public circuit geometry",
            "history": "Jolpica historical classification" if history else None,
        },
    }
    if history:
        jid = _JOLPICA_ID.get(out["name"])
        if jid:
            out["history"] = circuit_history(jid)
    if measure:
        from .race import load
        from .strategy import circuit_abrasion, stint_degradation
        from .survey import survey as _survey
        race = load(year, rnd)
        measured = _survey(race)
        # what the surface does to a tyre belongs with what the road does
        # to a car: both are properties of this circuit, and neither is on
        # any map of it
        abrasion = circuit_abrasion(race)
        rates = [s["degradation_s_per_lap"] for s in stint_degradation(race)
                 if s.get("degradation_s_per_lap") is not None]
        measured["surface"] = {
            **abrasion,
            "median_degradation_s_per_lap": (
                round(sorted(rates)[len(rates) // 2], 4) if rates else None),
            "stints_measured": len(rates),
            "measurement": "fuel-normalised clean laps; pit, safety-car and "
                           "traffic laps excluded",
        }
        # the published table is the reference and the cars are the
        # auditor: a stored figure cannot notice that it has gone stale,
        # and a measurement is far too coarse to publish but more than
        # sharp enough to catch one that has
        from .reference import audit, facts
        article = None
        jid = _JOLPICA_ID.get(out["name"])
        if jid:
            try:
                article = jolpica.get(f"circuits/{jid}")["CircuitTable"][
                    "Circuits"][0].get("url")
            except Exception:
                article = None
        published = facts(out["name"], article)
        if published:
            out["published"] = published
        out["audit"] = audit(out["name"], {
            "lap_distance_m": measured["elevation"].get("lap_distance_m"),
            "corners": out["corners"]}, article)
        out["measured"] = measured
        out["sources"]["measurement"] = (
            "this weekend's own position, car-data and stint telemetry")
        for key, block in (("elevation", measured["elevation"]),
                           ("drs_zones", measured["drs_zones"]),
                           ("track_width", measured["driven_corridor"])):
            out["layout"]["coverage"][key] = {
                "available": bool(block.get("available")),
                "reason": block.get("reason"),
                "measured_from": "session telemetry",
            }
    return jsonsafe(out)
