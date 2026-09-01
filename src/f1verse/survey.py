# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Surveying a circuit from the cars that drove it.

Map feeds hand over a flat outline: x and y, no height, no DRS zoning, no
sense of how wide the road is. All three of those facts are nonetheless
*recorded* every weekend — not by the map, but by the cars. Position
samples carry a ``z`` channel, so the elevation of the track is measured
several times a second by twenty vehicles. Car data carries the DRS
channel, so the zones announce themselves the moment a rear wing opens.
And a lap is a line, but a field of laps is a band: the spread of where
cars actually drove is the width of the road they used.

So this module measures rather than looks up. Everything here is derived
from telemetry this library already fetches, which means it works for any
session with position data, needs no third-party geometry service, and
cannot go stale against a resurfaced or re-profiled track — the cars
resurvey it every time they run.

What is measured is stated precisely. A corridor width is the width cars
*used*, which is a floor under the homologated track width and never a
claim about it. An elevation is relative to the feed's own datum, so
heights compare within a circuit and not between countries. Where the
samples do not support an answer, the answer is ``None`` with a reason.
"""
from __future__ import annotations

import math
from datetime import datetime

from ._json import jsonsafe
from .sources import openf1

# The position feed reports whole-number coordinates in tenths of a metre.
# Distances are converted once, here, so every public value in this module
# is metres and nothing downstream has to remember the scale.
UNITS_PER_METRE = 10.0

# DRS channel values that mean the wing is open. Lower values report the
# system as unavailable or merely armed in a detection zone, which is not
# the same thing as a zone being used.
_DRS_OPEN = {10, 12, 14}

# No Formula 1 circuit is 30 m wide, so a sample further than this from
# the racing line is on a different piece of road — the pit lane, most
# often, which runs alongside the track and would otherwise be measured
# as part of it.
MAX_HALF_WIDTH_M = 15.0

# A camber fit steeper than this is not a banked corner; it is a fit that
# has gone wrong, and it is reported as no answer. The ceiling is set well
# above the steepest banking in Formula 1 (Zandvoort, a little over 18
# degrees) so that only nonsense is rejected.
MAX_CREDIBLE_CAMBER = 40.0

# How far either side of a corner marker counts as being in the corner.
CORNER_SPAN_M = 60.0


def _fit_radius(points: list) -> float | None:
    """Radius of the circle that best fits an arc of the driven line.

    Every sample in the corner is used, which is what makes this steadier
    than reading a heading change between three of them: three points
    chord across the turn and report a corner flatter than it is, while a
    fit is pulled by the whole arc and lets position noise cancel. The
    algebra is the standard linearised circle fit, solved by elimination
    because this library carries no matrix library.
    """
    n = len(points)
    if n < 8:
        return None
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    # centring first keeps the normal equations well conditioned
    us = [p[0] - mx for p in points]
    vs = [p[1] - my for p in points]
    suu = sum(u * u for u in us)
    svv = sum(v * v for v in vs)
    suv = sum(u * v for u, v in zip(us, vs))
    suuu = sum(u ** 3 for u in us)
    svvv = sum(v ** 3 for v in vs)
    suvv = sum(u * v * v for u, v in zip(us, vs))
    svuu = sum(v * u * u for u, v in zip(us, vs))
    determinant = suu * svv - suv * suv
    if abs(determinant) < 1e-9:
        return None                       # a straight: no circle to fit
    rhs_u = (suuu + suvv) / 2
    rhs_v = (svvv + svuu) / 2
    cu = (rhs_u * svv - rhs_v * suv) / determinant
    cv = (rhs_v * suu - rhs_u * suv) / determinant
    radius = math.sqrt(max(cu * cu + cv * cv + (suu + svv) / n, 0.0))
    return radius or None


def _severity(apex_kph: float) -> str:
    """The vocabulary a track guide uses, tied to a measured speed."""
    if apex_kph < 100:
        return "slow"
    if apex_kph < 180:
        return "medium"
    return "fast"


def _epoch(stamp: str) -> float | None:
    try:
        return datetime.fromisoformat(stamp).timestamp()
    except (TypeError, ValueError):
        return None


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _fastest_lap(race) -> tuple:
    """The quickest completed lap of the session, as ``(driver, lap)``.

    A fast lap is the cleanest available survey line: the driver stayed on
    the road, took no defensive detour and did not lift, so the path is a
    fair sample of the circuit rather than of one racing incident.
    """
    best = None
    for row in race.laps:
        seconds = _finite(row.get("lap_duration"))
        if seconds and row.get("date_start"):
            if best is None or seconds < best[0]:
                best = (seconds, row["driver_number"], row["lap_number"])
    if best is None:
        raise LookupError("no timed lap in this session to survey from")
    return best[1], best[2]


def _lap_window(race, driver_number: int, lap: int) -> tuple:
    rows = [l for l in race.laps
            if l["driver_number"] == driver_number and l["lap_number"] == lap]
    if not rows or not rows[0].get("date_start"):
        raise LookupError(f"no start time for driver {driver_number} lap {lap}")
    start = datetime.fromisoformat(rows[0]["date_start"])
    from datetime import timedelta
    span = _finite(rows[0].get("lap_duration")) or 120.0
    return start.isoformat(), (start + timedelta(seconds=span + 1)).isoformat()


def _positions(race, driver_number: int, lap: int) -> list:
    """Position samples for one lap: ``(t, x, y, z)`` in metres."""
    lo, hi = _lap_window(race, driver_number, lap)
    rows = openf1.get("location", session_key=race.session_key,
                      driver_number=driver_number,
                      **{"date>=": lo, "date<=": hi})
    out = []
    for row in rows:
        t = _epoch(row.get("date"))
        x, y, z = (_finite(row.get("x")), _finite(row.get("y")),
                   _finite(row.get("z")))
        if None in (t, x, y):
            continue
        out.append((t, x / UNITS_PER_METRE, y / UNITS_PER_METRE,
                    None if z is None else z / UNITS_PER_METRE))
    return out


def _stations(samples: list) -> tuple:
    """Cumulative along-track distance for an ordered path, in metres."""
    walk, total = [0.0], 0.0
    for a, b in zip(samples, samples[1:]):
        total += math.hypot(b[1] - a[1], b[2] - a[2])
        walk.append(total)
    return walk, total


def _nearest(x: float, y: float, path: list) -> int:
    return min(range(len(path)),
               key=lambda i: (path[i][0] - x) ** 2 + (path[i][1] - y) ** 2)


def _normal(path: list, index: int) -> tuple:
    """Unit vector pointing across the track at one point of the path."""
    before = path[max(index - 1, 0)]
    after = path[min(index + 1, len(path) - 1)]
    dx, dy = after[0] - before[0], after[1] - before[1]
    length = math.hypot(dx, dy)
    if not length:
        return 0.0, 0.0
    return -dy / length, dx / length


# --- elevation ---------------------------------------------------------

def elevation(race, driver_number: int | None = None, lap: int | None = None,
              bins: int = 100) -> dict:
    """The height profile of the circuit, measured off a car.

    Position samples carry height, so one clean lap is a survey of the
    track's vertical shape. The profile is returned as ``bins`` stations
    around the lap, each with its distance from the line, its height above
    the lowest point of the circuit, and the gradient of the road there as
    a percentage.

    Heights are relative to this circuit's own lowest point, not to sea
    level: the feed's datum is not published, so an absolute altitude
    would be a number with no defensible meaning. Within a circuit the
    profile is exact, which is what a climb, a descent or a blind crest
    actually needs.
    """
    if driver_number is None or lap is None:
        driver_number, lap = _fastest_lap(race)
    samples = _positions(race, driver_number, lap)
    with_height = [s for s in samples if s[3] is not None]
    if len(with_height) < 20:
        return jsonsafe({
            "available": False,
            "reason": "position feed returned no height channel for this lap",
            "samples": len(with_height),
        })

    walk, total = _stations(with_height)
    floor = min(s[3] for s in with_height)
    stations = []
    for i in range(bins):
        target = total * i / bins
        j = min(range(len(walk)), key=lambda k: abs(walk[k] - target))
        stations.append({
            "distance_m": round(walk[j], 1),
            "lap_percent": round(100 * walk[j] / total, 2) if total else None,
            "height_m": round(with_height[j][3] - floor, 2),
        })
    for a, b in zip(stations, stations[1:]):
        run = b["distance_m"] - a["distance_m"]
        a["gradient_percent"] = (round(100 * (b["height_m"] - a["height_m"])
                                       / run, 2) if run else None)
    stations[-1]["gradient_percent"] = None

    heights = [s["height_m"] for s in stations]
    grades = [s["gradient_percent"] for s in stations
              if s["gradient_percent"] is not None]
    climbs = [g for g in grades if g > 0]
    return jsonsafe({
        "available": True,
        "measured_from": {"driver_number": driver_number, "lap": lap,
                          "samples": len(with_height)},
        "datum": "lowest point of this circuit",
        "total_rise_m": round(max(heights), 2),
        "steepest_climb_percent": round(max(grades), 2) if grades else None,
        "steepest_descent_percent": round(min(grades), 2) if grades else None,
        "total_climb_m": round(sum(
            b["height_m"] - a["height_m"] for a, b in zip(stations, stations[1:])
            if b["height_m"] > a["height_m"]), 1) if climbs else 0.0,
        "lap_distance_m": round(total, 1),
        "stations": stations,
    })


# --- DRS zones ---------------------------------------------------------

def _drs_channel_live(race) -> bool:
    """Whether this season's cars report a DRS state at all.

    From 2026 the field carries active aerodynamics instead of a drag
    reduction system. The field survives in the feed's schema but is never
    populated, so an empty result has two completely different meanings —
    "nobody needed it today" and "this car cannot do that" — and only one
    of them is about the weather.
    """
    for row in race.laps[:1] or []:
        try:
            probe = openf1.get("car_data", session_key=race.session_key,
                               driver_number=row["driver_number"],
                               **{"drs>=": 0})
        except Exception:
            return False
        return any(r.get("drs") is not None for r in probe)
    return False


def _drs_open_laps(race, driver_number: int) -> dict:
    """Laps on which a driver ran an open wing, and for how many samples.

    Asked of the whole session at once, filtered server-side to the open
    states, because looking lap by lap would be both slower and wrong: a
    car's quickest lap is usually its loneliest, and a driver with nobody
    within a second never opens the wing at all.
    """
    try:
        rows = openf1.get("car_data", session_key=race.session_key,
                          driver_number=driver_number,
                          **{"drs>=": min(_DRS_OPEN)})
    except Exception:
        # a car that never ran has no telemetry at all; that is one driver
        # missing, not a failed survey
        return {}
    stamps = sorted(t for t in (_epoch(r.get("date")) for r in rows
                                if r.get("drs") in _DRS_OPEN) if t is not None)
    if not stamps:
        return {}
    bounds = []
    for row in race.laps:
        if row["driver_number"] != driver_number or not row.get("date_start"):
            continue
        start = _epoch(row["date_start"])
        span = _finite(row.get("lap_duration"))
        if start is not None and span:
            bounds.append((start, start + span, row["lap_number"]))
    bounds.sort()
    tally = {}
    for stamp in stamps:
        for start, end, lap in bounds:
            if start <= stamp <= end:
                tally[lap] = tally.get(lap, 0) + 1
                break
    return tally


def drs_zones(race, drivers: int = 4, min_run_m: float = 80.0) -> dict:
    """Where DRS is actually used, found by watching wings open.

    No public map marks the zones, but every car announces them: the DRS
    channel changes state at the activation point and closes again under
    braking. The zones are therefore not looked up but observed.

    Which laps to read matters more than how many. A driver's fastest lap
    is typically run in clean air, which is exactly when DRS is *not*
    available — so this asks the session which laps had an open wing at
    all, and reads the busiest of those. Activations are pooled across
    several drivers and merged, and each zone reports the drivers whose
    data supports it. Runs shorter than ``min_run_m`` are treated as
    stray samples, not published as zones.
    """
    reference_driver, reference_lap = _fastest_lap(race)
    path_samples = _positions(race, reference_driver, reference_lap)
    if len(path_samples) < 20:
        return jsonsafe({"available": False,
                         "reason": "no position data to locate zones on"})
    path = [(s[1], s[2]) for s in path_samples]
    walk, total = _stations(path_samples)

    running = sorted({row["driver_number"] for row in race.laps})
    spans, examined = [], 0
    for num in running:
        if examined >= max(1, drivers):
            break
        busiest = _drs_open_laps(race, num)
        if not busiest:
            continue
        examined += 1
        lap = max(busiest, key=lambda k: busiest[k])
        lo, hi = _lap_window(race, num, lap)
        car = openf1.get("car_data", session_key=race.session_key,
                         driver_number=num, **{"date>=": lo, "date<=": hi})
        opens = sorted(t for t in
                       (_epoch(r.get("date")) for r in car
                        if r.get("drs") in _DRS_OPEN) if t is not None)
        positions = _positions(race, num, lap)
        if not opens or len(positions) < 20:
            continue
        # walk both series in time order and keep the station of each
        # position sample taken while the wing was open
        stations, cursor = [], 0
        for t, x, y, _z in positions:
            while cursor < len(opens) and opens[cursor] < t - 0.5:
                cursor += 1
            if cursor < len(opens) and abs(opens[cursor] - t) <= 0.5:
                stations.append(walk[_nearest(x, y, path)])
        if not stations:
            continue
        stations.sort()
        run = [stations[0]]
        for value in stations[1:]:
            if value - run[-1] <= 150.0:      # one gap-free stretch of road
                run.append(value)
            else:
                spans.append((run[0], run[-1], num))
                run = [value]
        spans.append((run[0], run[-1], num))

    if not spans:
        return jsonsafe({
            "available": False,
            "reason": ("this season's cars carry no DRS — the channel is "
                       "present in the feed but never set"
                       if not _drs_channel_live(race) else
                       "no DRS activation recorded in this session; a wet "
                       "race, or one spent behind a safety car, never "
                       "enables it"),
            "drivers_examined": examined,
            "successor": ("overtaking_zones — where passes actually happen, "
                          "which is the question DRS zones were a proxy for"),
        })

    merged = []
    for start, end, num in sorted(spans):
        if merged and start <= merged[-1]["end_m"] + 100.0:
            merged[-1]["end_m"] = max(merged[-1]["end_m"], end)
            merged[-1]["drivers"].add(num)
        else:
            merged.append({"start_m": start, "end_m": end, "drivers": {num}})

    zones = []
    for index, zone in enumerate(merged, start=1):
        length = zone["end_m"] - zone["start_m"]
        if length < min_run_m:
            continue
        zones.append({
            "zone": index,
            "start_m": round(zone["start_m"], 1),
            "end_m": round(zone["end_m"], 1),
            "length_m": round(length, 1),
            "start_lap_percent": (round(100 * zone["start_m"] / total, 2)
                                  if total else None),
            "drivers_observed": sorted(race.abbr(n) for n in zone["drivers"]),
        })
    return jsonsafe({
        "available": bool(zones),
        "reason": None if zones else "activations too short to be zones",
        "zones": zones,
        "drivers_examined": examined,
        "lap_distance_m": round(total, 1),
    })


# --- how wide the road is ----------------------------------------------

def _cross_slope(pairs: list) -> float | None:
    """Rise across the road per metre across it, as a percentage.

    Cars on different lines at the same point of the circuit are at
    different heights whenever the road is banked. Fitting height against
    lateral offset therefore recovers the camber without anyone
    surveying it — steeply positive at Zandvoort's banked turns, near
    zero on a flat straight. It needs a real spread of lines to mean
    anything, so a bunched-up sample declines to answer.
    """
    usable = [(lateral, z) for lateral, z in pairs if z is not None]
    if len(usable) < 12:
        return None
    laterals = [p[0] for p in usable]
    spread = max(laterals) - min(laterals)
    # a metre of spread is a wobble, not a cross-section: fitting a slope
    # to it turns position noise into imaginary banking
    if spread < 3.0:
        return None
    mean_x = sum(laterals) / len(usable)
    mean_z = sum(p[1] for p in usable) / len(usable)
    variance = sum((x - mean_x) ** 2 for x in laterals)
    if not variance:
        return None
    covariance = sum((x - mean_x) * (z - mean_z) for x, z in usable)
    slope = 100 * covariance / variance
    # a corner banked more steeply than any in Formula 1 is a bad fit, not
    # a discovery: say nothing rather than publish it
    if abs(slope) > MAX_CREDIBLE_CAMBER:
        return None
    return round(slope, 2)


def _spread_laps(race, drivers: int, laps: int) -> list:
    """``(driver, lap)`` pairs chosen to cover the road, not the racing line.

    Which laps are read decides what is being measured. Quick laps are all
    the same line: five of them agree to within centimetres and would
    report a road a foot wide. Two things break that sameness. The opening
    lap puts the field side by side, defending and running wide; and laps
    taken from across the race catch cars off line for every other reason
    — traffic, worn tyres, a lock-up. Both are needed, because the opening
    lap alone spreads the field only as far as the first few corners.
    """
    by_driver = {}
    for row in race.laps:
        if row.get("date_start") and _finite(row.get("lap_duration")):
            by_driver.setdefault(row["driver_number"], []).append(
                row["lap_number"])
    chosen = []
    for num in sorted(by_driver)[:max(2, drivers)]:
        numbers = sorted(by_driver[num])
        if not numbers:
            continue
        picks = {numbers[0]}                      # the opening lap always
        for step in range(1, max(1, laps)):
            picks.add(numbers[min(len(numbers) - 1,
                                  step * len(numbers) // max(1, laps))])
        chosen.extend((num, lap) for lap in sorted(picks))
    return chosen


def driven_corridor(race, drivers: int = 8, bins: int = 60,
                    laps: int = 3) -> dict:
    """How wide a band of road the field actually used.

    A single lap is a line. Many laps are a band, and the width of that
    band at each point of the circuit is a direct measurement of the road
    cars were willing to use there — narrow through a chicane, wide where
    the racing line crosses from kerb to kerb.

    This is deliberately not called track width. It is a **lower bound**
    on it: nobody is obliged to drive the last half-metre of asphalt, so
    the true road is at least this wide and usually a little wider. Stated
    that way it is a measurement; called track width it would be a guess.
    """
    reference_driver, reference_lap = _fastest_lap(race)
    reference = _positions(race, reference_driver, reference_lap)
    if len(reference) < 20:
        return jsonsafe({"available": False,
                         "reason": "no position data to measure against"})
    path = [(s[1], s[2]) for s in reference]
    walk, total = _stations(reference)

    chosen = _spread_laps(race, drivers, laps)

    offsets = {}
    counted, seen_drivers = 0, set()
    for num, lap in chosen:
        samples = _positions(race, num, lap)
        if len(samples) < 20:
            continue
        counted += 1
        seen_drivers.add(num)
        for _t, x, y, z in samples:
            index = _nearest(x, y, path)
            nx, ny = _normal(path, index)
            if not (nx or ny):
                continue
            lateral = (x - path[index][0]) * nx + (y - path[index][1]) * ny
            # a car in the pit lane is metres off the road but only a
            # short hop from a racing-line point, so without this it
            # would be measured as impossibly wide, impossibly banked
            # asphalt
            if abs(lateral) > MAX_HALF_WIDTH_M:
                continue
            station = int(bins * walk[index] / total) % bins if total else 0
            offsets.setdefault(station, []).append((lateral, z))

    if counted < 2:
        return jsonsafe({"available": False, "drivers_measured": counted,
                         "laps_measured": counted,
                         "reason": "need at least two laps to see a band"})

    sections = []
    for station in range(bins):
        pairs = sorted(offsets.get(station, []))
        values = [lateral for lateral, _z in pairs]
        if len(values) < 4:
            sections.append({"lap_percent": round(100 * station / bins, 2),
                             "used_width_m": None, "camber_index": None,
                             "samples": len(values)})
            continue
        # trim the extremes: one GPS excursion should not become a metre
        # of imaginary asphalt
        low = values[len(values) // 20]
        high = values[-1 - len(values) // 20]
        sections.append({
            "lap_percent": round(100 * station / bins, 2),
            "distance_m": round(total * station / bins, 1),
            "used_width_m": round(high - low, 2),
            "camber_index": _cross_slope(pairs),
            "samples": len(values),
        })

    widths = [s["used_width_m"] for s in sections if s["used_width_m"]]
    banks = [s["camber_index"] for s in sections
             if s["camber_index"] is not None]
    steepest = max(banks, key=abs) if banks else None
    return jsonsafe({
        "available": bool(widths),
        "measurement": (
            "the band of road the field used, section by section. "
            "`widest_m` is a lower bound on the track's real width, taken "
            "where cars ran side by side; `typical_spread_m` is much "
            "smaller and is not a width at all — it is how tightly the "
            "field agreed on the line where it ran in single file"),
        "drivers_measured": len(seen_drivers),
        "laps_measured": counted,
        "widest_m": round(max(widths), 2) if widths else None,
        "typical_spread_m": (round(sorted(widths)[len(widths) // 2], 2)
                             if widths else None),
        # Cars on different lines at the same point sit at different
        # heights exactly when the road is banked, so the field detects
        # camber for free — but only detects it. Checked against
        # Zandvoort, whose final corner is banked a little over 18
        # degrees, this reads about a quarter of the true slope: noise in
        # a car's measured lateral position drags any fitted slope toward
        # zero. The index is therefore published for comparing one part
        # of a circuit with another, never as an angle.
        "steepest_camber_index": steepest,
        "camber_note": ("relative indicator, not an angle: it locates "
                        "banking and gives its direction, and understates "
                        "its steepness by roughly a factor of four"),
        "lap_distance_m": round(total, 1),
        "sections": sections,
    })


# --- where the racing actually happens ---------------------------------

def _lap_template(samples: list) -> list:
    """``(fraction of lap elapsed, distance travelled)`` for one lap.

    A lap is not driven at a constant rate, so half the time is not half
    the road. This records how one real lap converted time into distance,
    which lets any other timestamped event be placed on the circuit
    without fetching that car's position separately.
    """
    walk, total = _stations(samples)
    span = samples[-1][0] - samples[0][0]
    if not span or not total:
        return []
    return [((s[0] - samples[0][0]) / span, d) for s, d in zip(samples, walk)]


def _place(fraction: float, template: list) -> float | None:
    if not template:
        return None
    fraction = min(max(fraction, 0.0), 1.0)
    for (f0, d0), (f1, d1) in zip(template, template[1:]):
        if f0 <= fraction <= f1:
            if f1 == f0:
                return d0
            return d0 + (d1 - d0) * (fraction - f0) / (f1 - f0)
    return template[-1][1]


def overtaking_zones(race, min_passes: int = 3) -> dict:
    """Where on this circuit cars actually pass each other.

    This is the question a DRS-zone map was only ever a proxy for, and
    unlike DRS it does not depend on a regulation that comes and goes: as
    long as cars overtake, the passes can be located. Every on-track pass
    the timing feed recorded is placed on the lap by converting its
    timestamp through a real lap's own time-to-distance curve, then the
    passes are clustered into the stretches of road where they concentrate.

    The placement is a lap template rather than a per-pass position
    lookup — hundreds of passes would otherwise mean hundreds of requests
    — so a zone's extent is accurate to a corner, not to a metre. Each
    zone reports how many passes built it.
    """
    try:
        passes = openf1.get("overtakes", session_key=race.session_key)
    except Exception:
        return jsonsafe({
            "available": False,
            "reason": "this session publishes no overtake feed "
                      "(sprints and older seasons have none)"})
    if not passes:
        return jsonsafe({"available": False,
                         "reason": "no on-track passes were recorded"})

    driver, lap = _fastest_lap(race)
    samples = _positions(race, driver, lap)
    if len(samples) < 20:
        return jsonsafe({"available": False,
                         "reason": "no position data to place passes on"})
    template = _lap_template(samples)
    _walk, total = _stations(samples)

    laps_by_driver = {}
    for row in race.laps:
        start, span = _epoch(row.get("date_start")), _finite(row.get("lap_duration"))
        if start is not None and span:
            laps_by_driver.setdefault(row["driver_number"], []).append(
                (start, start + span, row["lap_number"]))

    located, unplaced = [], 0
    for row in passes:
        when = _epoch(row.get("date"))
        num = row.get("overtaking_driver_number")
        window = next((w for w in laps_by_driver.get(num, [])
                       if w[0] <= (when or -1) <= w[1]), None)
        if when is None or window is None:
            unplaced += 1
            continue
        start, end, lap_number = window
        station = _place((when - start) / (end - start), template)
        if station is None:
            unplaced += 1
            continue
        located.append((station, num, row.get("overtaken_driver_number"),
                        lap_number))
    if not located:
        return jsonsafe({"available": False, "passes_recorded": len(passes),
                         "reason": "no pass could be tied to a timed lap"})

    located.sort()
    reach = max(120.0, total * 0.03)
    clusters, run = [], [located[0]]
    for item in located[1:]:
        if item[0] - run[-1][0] <= reach:
            run.append(item)
        else:
            clusters.append(run)
            run = [item]
    clusters.append(run)
    # a circuit is a loop: the braking zone for turn one sits on both
    # sides of the timing line, and splitting it there would report the
    # busiest overtaking spot on the track as two lesser ones
    if (len(clusters) > 1
            and total - clusters[-1][-1][0] + clusters[0][0][0] <= reach):
        clusters[0] = clusters.pop() + clusters[0]

    zones = []
    for index, run in enumerate(sorted(clusters, key=len, reverse=True), 1):
        if len(run) < min_passes:
            continue
        zones.append({
            "rank": index,
            "start_m": round(run[0][0], 1),
            "end_m": round(run[-1][0], 1),
            "crosses_start_line": run[-1][0] < run[0][0],
            "lap_percent": round(100 * run[0][0] / total, 2) if total else None,
            "passes": len(run),
            "share_of_passes": round(len(run) / len(located), 3),
            "top_aggressors": sorted({race.abbr(r[1]) for r in run})[:5],
        })
    return jsonsafe({
        "available": bool(zones),
        "reason": None if zones else "passes were too scattered to form a zone",
        "zones": zones,
        "passes_recorded": len(passes),
        "passes_located": len(located),
        "passes_unplaced": unplaced,
        "placement": "lap-time template; accurate to a corner, not a metre",
        "lap_distance_m": round(total, 1),
    })


# --- what the lap demands of a car -------------------------------------

def character(race, driver_number: int | None = None,
              lap: int | None = None) -> dict:
    """How much of this lap is spent flat out, and where it is braked.

    Circuit previews describe tracks as power tracks or downforce tracks
    on the strength of exactly two numbers — the share of the lap at full
    throttle and the number and severity of braking events. Both are
    published as marketing by suppliers and neither is in any open
    dataset, yet both are sitting in the car data of every session.

    Braking zones are reported with the speed carried in, the minimum
    speed reached and the metres spent on the pedal, which is the shape
    of the corner as the car experienced it rather than as a map drew it.
    """
    if driver_number is None or lap is None:
        driver_number, lap = _fastest_lap(race)
    samples = _positions(race, driver_number, lap)
    if len(samples) < 20:
        return jsonsafe({"available": False,
                         "reason": "no position data for this lap"})
    walk, total = _stations(samples)
    lo, hi = _lap_window(race, driver_number, lap)
    rows = openf1.get("car_data", session_key=race.session_key,
                      driver_number=driver_number,
                      **{"date>=": lo, "date<=": hi})
    car = sorted(((_epoch(r.get("date")), r) for r in rows
                  if _epoch(r.get("date")) is not None))
    if len(car) < 20:
        return jsonsafe({"available": False,
                         "reason": "no car data for this lap"})

    # give every car-data row the station of the nearest position sample
    placed, cursor = [], 0
    for when, row in car:
        while cursor + 1 < len(samples) and samples[cursor + 1][0] <= when:
            cursor += 1
        placed.append((walk[cursor], row))

    flat, braking_m, previous_speed = 0.0, 0.0, None
    zones, current = [], None
    for (station, row), (next_station, _) in zip(placed, placed[1:]):
        step = max(next_station - station, 0.0)
        throttle = _finite(row.get("throttle")) or 0.0
        brake = _finite(row.get("brake")) or 0.0
        speed = _finite(row.get("speed"))
        if throttle >= 99:
            flat += step
        if brake > 0:
            braking_m += step
            if current is None:
                # the speed carried into the zone is the one from just
                # before the pedal went down; by the first braking sample
                # the car is already slowing
                entry = previous_speed if previous_speed is not None else speed
                current = {"start_m": station, "entry_kph": entry,
                           "min_kph": speed, "length_m": 0.0}
            current["length_m"] += step
            if speed is not None and (current["min_kph"] is None
                                      or speed < current["min_kph"]):
                current["min_kph"] = speed
        elif current is not None:
            if current["length_m"] >= 20:
                zones.append(current)
            current = None
        previous_speed = speed
    if current is not None and current["length_m"] >= 20:
        zones.append(current)

    speeds = [_finite(r.get("speed")) for _s, r in placed]
    speeds = [s for s in speeds if s is not None]
    for index, zone in enumerate(zones, start=1):
        zone.update({
            "zone": index,
            "start_m": round(zone["start_m"], 1),
            "length_m": round(zone["length_m"], 1),
            "entry_kph": round(zone["entry_kph"]) if zone["entry_kph"] else None,
            "min_kph": round(zone["min_kph"]) if zone["min_kph"] else None,
        })
        zone["speed_shed_kph"] = (
            zone["entry_kph"] - zone["min_kph"]
            if zone["entry_kph"] and zone["min_kph"] else None)
    hardest = max(zones, key=lambda z: z["speed_shed_kph"] or 0, default=None)
    return jsonsafe({
        "available": True,
        "measured_from": {"driver": race.abbr(driver_number), "lap": lap},
        "lap_distance_m": round(total, 1),
        "full_throttle_percent": round(100 * flat / total, 1) if total else None,
        "braking_percent": round(100 * braking_m / total, 1) if total else None,
        "braking_zones": len(zones),
        "hardest_braking_zone": hardest,
        "top_speed_kph": round(max(speeds)) if speeds else None,
        "minimum_speed_kph": round(min(speeds)) if speeds else None,
        "zones": zones,
    })


def survey(race, drivers: int = 6, laps: int = 3) -> dict:
    """Everything a car can tell us about the shape of a circuit.

    Elevation, DRS zoning and used width in one call, each carrying its
    own availability and evidence so a caller can use the parts that came
    back and see why anything missing is missing.
    """
    return jsonsafe({
        "event": {"year": race.year, "round": race.round,
                  "session": race.name},
        "elevation": elevation(race),
        "character": character(race),
        "corners": corner_dossier(race),
        "overtaking_zones": overtaking_zones(race),
        "driven_corridor": driven_corridor(race, drivers=drivers, laps=laps),
        "drs_zones": drs_zones(race, drivers=drivers),
        "note": "measured from this session's own position and car data; "
                "no external geometry service is involved",
    })


# --- what each numbered corner actually demands ------------------------

def corner_dossier(race, driver_number: int | None = None,
                   lap: int | None = None) -> dict:
    """Every numbered corner, measured as the car experienced it.

    A map says corner 3 exists and points north-east. It cannot say how
    fast the corner is taken, how hard it is braked for, or how much grip
    it asks of the car — and those are the things that decide a lap.

    Cornering load is computed from the path and the speedometer rather
    than from height, which is what makes it trustworthy where a camber
    fit is not: the curvature of a line is recoverable by measuring the
    heading change over tens of metres, which averages position noise
    away, while a cross-slope has to resolve centimetres of height across
    a few metres of width and cannot. The lateral load is therefore a
    real number with a unit, and it can be checked against physics — a
    Formula 1 car sustains roughly 4 to 6 g in a quick corner.
    """
    from .circuit import layout_diagnostics
    from .sources import multiviewer

    if driver_number is None or lap is None:
        driver_number, lap = _fastest_lap(race)
    samples = _positions(race, driver_number, lap)
    if len(samples) < 40:
        return jsonsafe({"available": False,
                         "reason": "not enough position data for this lap"})
    walk, total = _stations(samples)

    try:
        geometry = multiviewer.circuit(race.meeting["circuit_key"], race.year)
        corners = layout_diagnostics(geometry).get("corners", [])
    except Exception:
        return jsonsafe({"available": False,
                         "reason": "no corner numbering available for this circuit"})
    if not corners:
        return jsonsafe({"available": False, "reason": "no corners published"})

    lo, hi = _lap_window(race, driver_number, lap)
    rows = openf1.get("car_data", session_key=race.session_key,
                      driver_number=driver_number,
                      **{"date>=": lo, "date<=": hi})
    car = sorted(((_epoch(r.get("date")), r) for r in rows
                  if _epoch(r.get("date")) is not None))
    if len(car) < 40:
        return jsonsafe({"available": False, "reason": "no car data for this lap"})
    placed, cursor = [], 0
    for when, row in car:
        while cursor + 1 < len(samples) and samples[cursor + 1][0] <= when:
            cursor += 1
        placed.append((walk[cursor], row))

    def _at(station: float, span: float) -> list:
        return [(s, r) for s, r in placed if abs(s - station) <= span]

    out = []
    for corner in corners:
        progress = corner.get("progress_pct")
        if progress is None:
            continue
        station = total * progress / 100
        near = _at(station, CORNER_SPAN_M)
        if len(near) < 3:
            continue
        speeds = [(_finite(r.get("speed")), s, r) for s, r in near]
        speeds = [t for t in speeds if t[0] is not None]
        if not speeds:
            continue
        apex_speed, apex_station, apex_row = min(speeds, key=lambda t: t[0])
        approach = [_finite(r.get("speed")) for s, r in
                    _at(station - 2 * CORNER_SPAN_M, CORNER_SPAN_M)]
        approach = [v for v in approach if v is not None]
        # A car crossing a fast corner at 280 km/h leaves a sample only
        # every twenty metres, so a fixed window that is generous in a
        # hairpin holds too few points to fit anything here. Widen until
        # there is an arc to fit, and give up rather than guess.
        radius, span = None, CORNER_SPAN_M
        while radius is None and span <= 3 * CORNER_SPAN_M:
            arc = [(samples[i][1], samples[i][2]) for i in range(len(samples))
                   if abs(walk[i] - apex_station) <= span]
            radius = _fit_radius(arc)
            span += 30.0
        load = (None if not radius else
                round((apex_speed / 3.6) ** 2 / radius / 9.81, 2))
        out.append({
            "corner": corner.get("number"),
            "lap_percent": progress,
            "distance_m": round(station, 1),
            "apex_speed_kph": round(apex_speed),
            "entry_speed_kph": round(max(approach)) if approach else None,
            "speed_shed_kph": (round(max(approach) - apex_speed)
                               if approach else None),
            "radius_m": round(radius, 1) if radius else None,
            "lateral_load_g": load,
            "gear_at_apex": apex_row.get("n_gear"),
            "severity": _severity(apex_speed),
        })
    loads = [c["lateral_load_g"] for c in out if c["lateral_load_g"]]
    return jsonsafe({
        "available": bool(out),
        "measured_from": {"driver": race.abbr(driver_number), "lap": lap},
        "corners": out,
        "slowest_corner": min(out, key=lambda c: c["apex_speed_kph"], default=None),
        "highest_load_g": max(loads) if loads else None,
        "method": "cornering load from a circle fitted to the driven arc "
                  "and the speed carried through it; the fit uses every "
                  "sample in the corner, so position noise cancels",
    })
