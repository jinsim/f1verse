# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Undercut / overcut verdicts — did the stop actually gain anything?

An undercut works when a driver pits first, runs fresh rubber while the
rival stays out, and emerges ahead. Whether it *worked* is a factual
question about the gap before and after the exchange, and this module
answers it with the circuit's real pit loss as the yardstick.
"""
from __future__ import annotations

from ._json import jsonsafe
from ._evidence import evidence
import math


def _gap_at(race, drv_num, lap):
    """Seconds behind the leader at a lap, from the interval feed if
    available, else derived from cumulative lap times."""
    laps = [l for l in race.laps if l["driver_number"] == drv_num
            and l["lap_number"] <= lap and l.get("lap_duration")]
    return sum(l["lap_duration"] for l in laps) if laps else None


def circuit_pit_loss(race) -> dict:
    """Seconds a stop costs at this circuit, split by track state.

    A stop under a safety car is cheap because the field is crawling; the
    same stop at racing speed is not. The undercut verdicts below use the
    ``normal`` figure as their yardstick, and report it, so the reader can
    see what "gained 2.1 s" was measured against.
    """
    try:
        from .circuit import profile
        loss = profile(race.year, race.round, history=False)["pit_loss_s"]
    except Exception:
        return {}
    return {k: round(float(v), 3) for k, v in (loss or {}).items()}


def pit_exchanges(race, pit_loss_s: float | None = None,
                  window: int = 4, *, resolve_pit_loss: bool = True) -> list:
    """Every genuine undercut attempt, with a verdict.

    For each stop, find the driver immediately ahead who had *not* yet
    stopped, and compare relative time before the stop and after both have
    stopped. Positive ``gain_s`` means the stopper came out better off.

    Two classes of stop are excluded, because calling them undercuts would
    be wrong: stops made while the race is neutralised (red flag, safety
    car, VSC — everyone pits at once and nobody is undercutting anyone),
    and stops where the rival responded on the same lap, which is a
    covering stop rather than an undercut.
    """
    if pit_loss_s is None and resolve_pit_loss:
        pit_loss_s = circuit_pit_loss(race).get("normal")
    neutralised = {l for a, b in race.interruptions()["sc_vsc_bands"]
                   for l in range(a, b + 2)}
    neutralised |= {l for r in race.interruptions()["red_flag_laps"]
                    for l in (r, r + 1)}
    stops = sorted((p for p in race.pits
                    if p["lap_number"] not in neutralised),
                   key=lambda p: (p["lap_number"], p["driver_number"]))
    stopped_at = {}
    for p in stops:
        stopped_at.setdefault(p["driver_number"], []).append(p["lap_number"])

    # position by lap, from the lap table order
    pos = {}
    for l in race.laps:
        if l.get("date_start"):
            pos.setdefault(l["lap_number"], []).append(
                (l["date_start"], l["driver_number"]))
    order = {ln: [n for _, n in sorted(v)] for ln, v in pos.items()}

    out = []
    for p in stops:
        lap, me = p["lap_number"], p["driver_number"]
        before = order.get(lap - 1) or order.get(lap) or []
        if me not in before:
            continue
        i = before.index(me)
        if i == 0:
            continue
        rival = before[i - 1]
        rival_stops = [l for l in stopped_at.get(rival, []) if l >= lap]
        if not rival_stops:
            continue                      # rival never responded
        rival_lap = rival_stops[0]
        if rival_lap <= lap:
            continue                      # covering stop, not an undercut
        if rival_lap - lap > window:
            continue                      # too far apart to be a response
        after = rival_lap + 2             # both on fresh tyres
        if any(l in neutralised for l in range(lap - 1, after + 1)):
            continue  # a neutralisation between stops also confounds the exchange
        needed = set(range(lap, after + 1))
        if any(not needed.issubset({l["lap_number"] for l in race.laps
                                   if l["driver_number"] == n and l.get("lap_duration")})
               for n in (me, rival)):
            continue
        pre = (_gap_at(race, me, lap - 1), _gap_at(race, rival, lap - 1))
        post = (_gap_at(race, me, after), _gap_at(race, rival, after))
        if None in pre or None in post:
            continue
        gain = (pre[0] - pre[1]) - (post[0] - post[1])
        kind = "undercut"
        out.append({
            "lap": lap, "driver": race.abbr(me), "rival": race.abbr(rival),
            "rival_pitted_lap": rival_lap, "kind": kind,
            "gain_s": round(gain, 3),
            "verdict": "worked" if gain > 0.5 else
                       "failed" if gain < -0.5 else "neutral",
            "pit_loss_reference_s": pit_loss_s,
            # what the move recovered, as a share of the stop it cost
            "share_of_pit_loss": (round(gain / pit_loss_s, 3)
                                  if pit_loss_s else None),
            "kind_of_claim": "observed_comparison", "causal_effect_s": None,
            "limitations": ["opponents react; traffic and tyre differences are not isolated"],
        })
    return jsonsafe(sorted(out, key=lambda e: e["lap"]))


# --- tyre life ---------------------------------------------------------
#
# A raw lap-time trend mixes two stories: the tyre giving up, and the car
# getting lighter. A race car sheds roughly a lap of fuel every lap, and
# carrying fuel costs time, so the car speeds up all race for reasons that
# have nothing to do with rubber. Strip that out first, or every
# degradation number is an understatement.

FUEL_START_KG = 110.0       # legacy illustrative assumption, not measured fuel
FUEL_BURN_KG_PER_LAP = 1.6
FUEL_COST_S_PER_KG = 0.032


def _fuel_model(race=None, model=None):
    year = getattr(race, "year", None)
    if model is None and year is not None and year >= 2026:
        return {"available": False, "scope": "unsupported_era",
                "reason": "2026+ fuel and energy effects are not calibrated",
                "year": year}
    values = dict(model) if model is not None else {
        "start_kg": FUEL_START_KG, "burn_kg_per_lap": FUEL_BURN_KG_PER_LAP,
        "cost_s_per_kg": FUEL_COST_S_PER_KG}
    required = {"start_kg", "burn_kg_per_lap", "cost_s_per_kg"}
    if set(values) != required or any(
            isinstance(v, bool) or not isinstance(v, (int, float))
            or not math.isfinite(v) or v < 0 for v in values.values()):
        raise ValueError("fuel_model needs finite nonnegative start_kg, "
                         "burn_kg_per_lap and cost_s_per_kg")
    return {**values, "available": True, "year": year,
            "scope": "caller_scenario" if model is not None else "legacy_scenario",
            "reason": "assumed coefficients; fuel load is not observed"}


def fuel_normalised(lap_time_s: float, lap_number: int, *, fuel_model=None) -> float:
    """A lap time with the weight of the remaining fuel priced out.

    The returned value answers "what would this lap have cost on an empty
    tank", which makes laps from different points in the race comparable.
    """
    if (isinstance(lap_number, bool) or not isinstance(lap_number, int) or lap_number < 1
            or not isinstance(lap_time_s, (int, float)) or not math.isfinite(lap_time_s)
            or lap_time_s <= 0):
        raise ValueError("lap_time_s must be finite and positive; lap_number must be a positive integer")
    model = _fuel_model(model=fuel_model)
    on_board = max(model["start_kg"] - (lap_number - 1) * model["burn_kg_per_lap"], 0.0)
    return lap_time_s - model["cost_s_per_kg"] * on_board


def _trend(points: list) -> float | None:
    """Seconds-per-lap trend of ``[(lap, seconds), ...]``.

    The median of all pairwise slopes, not a least-squares fit: one lap
    ruined by traffic or a slow zone drags a regression line but barely
    moves a median. Needs at least two distinct laps.
    """
    slopes = sorted((s2 - s1) / (l2 - l1)
                    for i, (l1, s1) in enumerate(points)
                    for l2, s2 in points[i + 1:] if l2 != l1)
    if not slopes:
        return None
    n = len(slopes)
    mid = slopes[n // 2]
    return mid if n % 2 else (slopes[n // 2 - 1] + mid) / 2


def _clean_stint_laps(race, drv_num: int, first: int, last: int, *,
                      fuel_model=None, raw=False) -> list:
    """``(lap, fuel-normalised seconds)`` for the representative laps of a
    stint — pit laps, neutralised laps and obvious traffic excluded, per
    the same domain defaults ``race_pace`` applies."""
    bands = race.interruptions()
    slow = {l for a, b in bands["sc_vsc_bands"] for l in range(a, b + 2)}
    slow |= {l for r in bands["red_flag_laps"] for l in (r, r + 1)}
    boxed = {p["lap_number"] for p in race.pits
             if p["driver_number"] == drv_num}
    boxed |= {l + 1 for l in boxed}
    rows = [(l["lap_number"], l["lap_duration"]) for l in race.laps
            if l["driver_number"] == drv_num and l.get("lap_duration")
            and first <= l["lap_number"] <= last
            and l["lap_number"] not in slow | boxed]
    if not rows:
        return []
    ref = sorted(t for _, t in rows)[len(rows) // 2]
    model = _fuel_model(race, fuel_model)
    coeffs = {k: model[k] for k in ("start_kg", "burn_kg_per_lap", "cost_s_per_kg")} \
        if model["available"] else None
    return [(ln, t if raw or not model["available"] else
             fuel_normalised(t, ln, fuel_model=coeffs))
            for ln, t in rows if t <= ref * 1.07]


def stint_degradation(race, min_laps: int = 5, *, fuel_model=None) -> list:
    """How fast each set of tyres went off, stint by stint.

    One entry per stint, with the evidence the number was computed from:
    which laps were kept, how many were thrown out and why. A stint with
    fewer than ``min_laps`` clean laps gets no rate rather than a shaky
    one — ``reason`` says so explicitly.
    """
    if isinstance(min_laps, bool) or not isinstance(min_laps, int) or min_laps < 2:
        raise ValueError("min_laps must be an integer >= 2")
    model = _fuel_model(race, fuel_model)
    out = []
    for s in sorted(race.stints_raw,
                    key=lambda s: (s.get("driver_number") or 0,
                                   s.get("stint_number") or 0)):
        num = s.get("driver_number")
        first, last = s.get("lap_start"), s.get("lap_end")
        if num is None or first is None or last is None:
            continue
        clean = _clean_stint_laps(race, num, first, last, fuel_model=fuel_model)
        raw = _clean_stint_laps(race, num, first, last, raw=True)
        entry = {
            "driver": race.abbr(num),
            "stint": s.get("stint_number"),
            "compound": (s.get("compound") or "UNKNOWN").upper(),
            "laps": [first, last],
            "tyre_age_at_start": s.get("tyre_age_at_start"),
            "clean_laps_used": len(clean),
            "raw_trend_s_per_lap": round(_trend(raw), 4) if len(raw) >= min_laps else None,
            "fuel_model": model,
            "evidence": evidence("median_pairwise_slope", {
                "year": getattr(race, "year", None), "driver_number": num,
                "stint": s.get("stint_number"), "raw_points": raw, "fuel_model": model},
                sample_unit="lap within one stint", samples=len(clean),
                assumptions=[model["reason"], "not a causal estimate of tyre wear"],
                exclusions=["pit and following lap", "SC/VSC and restart lap",
                            "red flag and following lap", "laps >107% of stint median"]),
        }
        if not model["available"]:
            entry.update({"degradation_s_per_lap": None,
                          "reason": model["reason"]})
        elif len(clean) < min_laps:
            entry.update({"degradation_s_per_lap": None,
                          "reason": "too few clean laps"})
        else:
            rate = _trend(clean)
            entry.update({
                "degradation_s_per_lap": round(rate, 4),
                "fuel_normalised_pace_s":
                    round(sorted(t for _, t in clean)[len(clean) // 2], 3),
            })
            # Refit both scenarios, including any assumed empty-tank clamp.
            sensitivity = []
            for multiplier in (0.75, 1.25):
                coeffs = {k: model[k] for k in ("start_kg", "burn_kg_per_lap", "cost_s_per_kg")}
                coeffs["burn_kg_per_lap"] *= multiplier
                sensitivity.append(_trend([(l, fuel_normalised(t, l, fuel_model=coeffs))
                                           for l, t in raw]))
            entry["fuel_sensitivity_s_per_lap"] = {
                "kind": "scenario_range", "burn_multiplier": [0.75, 1.25],
                "range": [round(v, 4) for v in sorted(sensitivity)],
                "note": "refitted fuel-burn scenarios, not statistical uncertainty"}
        out.append(entry)
    return jsonsafe(out)


# What one lap on each slick compound is expected to cost at a circuit of
# ordinary roughness. Dividing a measured rate by this makes stints on
# different compounds comparable.
_ORDINARY_WEAR_S_PER_LAP = {"SOFT": 0.015, "MEDIUM": 0.009, "HARD": 0.003}


def circuit_abrasion(race, min_laps: int = 8, *, fuel_model=None) -> dict:
    """How hard this surface is on tyres, relative to an ordinary circuit.

    Each long-enough stint contributes its degradation rate divided by
    what that compound ordinarily loses per lap; the estimate is the
    median of those ratios, held to [0.7, 1.4] because a handful of
    stints cannot credibly say more. ``samples`` is the evidence — with
    fewer than three the verdict is ``"unknown"``, not a guess.
    """
    ratios = []
    for e in stint_degradation(race, min_laps=min_laps, fuel_model=fuel_model):
        base = _ORDINARY_WEAR_S_PER_LAP.get(e["compound"])
        rate = e.get("degradation_s_per_lap")
        if base and rate is not None and rate > 0:
            ratios.append(rate / base)
    if len(ratios) < 3:
        return jsonsafe({"factor": None, "verdict": "unknown",
                         "samples": len(ratios), "fuel_model": _fuel_model(race, fuel_model),
                         "reason": "fewer than three usable positive corrected stint trends"})
    raw = sorted(ratios)[len(ratios) // 2]
    factor = min(max(raw, 0.7), 1.4)
    return jsonsafe({
        "factor": round(factor, 3),
        # a clamped value is a floor, not a reading: say so rather than let
        # "1.4" be mistaken for a measurement that happened to land there
        "at_limit": raw != factor,
        "verdict": ("abrasive" if factor > 1.05 else
                    "smooth" if factor < 0.95 else "ordinary"),
        "samples": len(ratios),
        "kind": "scenario_index", "fuel_model": _fuel_model(race, fuel_model),
    })


def _running_pace(points: list, expected_rate: float,
                  lap_noise_s: float = 0.3, drift_s: float = 0.1) -> tuple:
    """``(pace_now_s, uncertainty_s)`` after walking a stint lap by lap.

    A running estimate that starts from the tyre's expected loss per lap
    and hands weight to the observed laps as they accumulate — early in a
    stint the expectation does most of the talking, twenty laps in the
    stopwatch does. ``lap_noise_s`` is how much an individual lap wobbles
    for reasons that are not the tyre; ``drift_s`` is how much the true
    pace can move between laps beyond the modelled wear. The update is
    two lines of arithmetic, deliberately — an estimate a reader cannot
    re-derive by hand has no place under a published number.
    """
    (lap0, mu), var = points[0], lap_noise_s ** 2
    prev = lap0
    history = [points[0]]
    for lap, seconds in points[1:]:
        # Learn drift from past laps only; a misspecified wear prior must
        # not leave a permanent bias once the stint supplies evidence.
        observed = _trend(history) if len(history) >= 3 else None
        rate = ((expected_rate + (len(history) - 2) * observed) / (len(history) - 1)
                if observed is not None else expected_rate)
        ahead = (lap - prev) * rate
        var += drift_s ** 2 * (lap - prev)
        weight = var / (var + lap_noise_s ** 2)
        # the more the stopwatch is trusted, the less the wear model adds
        mu += ahead + weight * (seconds - (mu + ahead))
        var *= (1 - weight)
        prev = lap
        history.append((lap, seconds))
    return mu, var ** 0.5


def tyre_outlook(race, cliff_s: float = 1.0, *, fuel_model=None) -> list:
    """Where each driver's current rubber is heading.

    For the last stint on record per driver: the fuel-normalised pace the
    tyre is doing *now*, the trend it is on, and how many more laps until
    it has given up ``cliff_s`` relative to today — with the sample size
    that estimate stands on. Stints too short to read return the fields
    as ``None`` and say why; a number this forward-looking must never
    pretend to more evidence than it has.
    """
    if not math.isfinite(cliff_s) or cliff_s <= 0:
        raise ValueError("cliff_s must be finite and positive")
    model = _fuel_model(race, fuel_model)
    latest = {}
    for s in race.stints_raw:
        num = s.get("driver_number")
        if num is not None and (num not in latest
                                or (s.get("stint_number") or 0)
                                > (latest[num].get("stint_number") or 0)):
            latest[num] = s
    out = []
    for num, s in sorted(latest.items()):
        first, last = s.get("lap_start"), s.get("lap_end")
        compound = (s.get("compound") or "UNKNOWN").upper()
        entry = {"driver": race.abbr(num), "compound": compound,
                 "stint": s.get("stint_number"), "fuel_model": model,
                 "claim_kind": "scenario", "physical_tyre_life": None}
        clean = _clean_stint_laps(race, num, first or 0, last or 0,
                                  fuel_model=fuel_model) \
            if first and last else []
        entry["evidence"] = evidence("adaptive_drift_pace_filter", {
            "points": clean, "driver_number": num, "fuel_model": model,
            "threshold_s": cliff_s, "stint": s.get("stint_number")},
            sample_unit="clean lap within last observed stint", samples=len(clean),
            kind="scenario", assumptions=["future drift held constant", model["reason"]],
            exclusions=["pit, neutralisation and conspicuously slow laps"],
            uncertainty={"kind": "conditional_filter_standard_deviation; drift uncertainty omitted"})
        if len(clean) < 4 or not model["available"]:
            entry.update({"pace_now_s": None, "trend_s_per_lap": None,
                          "laps_to_cliff": None,
                          "reason": "too few clean laps" if model["available"] else model["reason"],
                          "clean_laps_used": len(clean)})
            out.append(entry)
            continue
        rate = _trend(clean)
        expected = rate if rate and rate > 0 else \
            _ORDINARY_WEAR_S_PER_LAP.get(compound, 0.01)
        pace, sd = _running_pace(clean, expected)
        entry.update({
            "pace_now_s": round(pace, 3),
            "uncertainty_s": round(sd, 3),
            "trend_s_per_lap": round(expected, 4),
            "laps_to_cliff": (int(cliff_s / expected)
                              if expected > 1e-4 else None),
            "clean_laps_used": len(clean),
            "uncertainty_kind": "conditional_filter_standard_deviation",
            "trend_source": "fitted" if rate and rate > 0 else "compound_prior",
            "limitations": ["not a prediction interval", "pit timing is a strategy decision",
                            "constant trend extrapolation, not physical tyre life"],
        })
        out.append(entry)
    return jsonsafe(out)


def pace_changes(race, min_laps: int = 5, threshold_s: float = 0.75, *,
                 fuel_model=None) -> dict:
    """Retrospective persistent pace shifts, without claiming their cause.

    Compare adjacent windows after removing the median adjacent-lap trend.
    Windows never cross missing/excluded laps or stint boundaries. The
    threshold is an effect-size rule, not a significance test. Future laps
    are required: this is deliberately not a live detector.
    """
    from statistics import median
    if isinstance(min_laps, bool) or not isinstance(min_laps, int) or min_laps < 3:
        raise ValueError("min_laps must be an integer >= 3")
    if not math.isfinite(threshold_s) or threshold_s <= 0:
        raise ValueError("threshold_s must be finite and positive")
    changes, inputs, windows_compared = [], [], 0
    for stint in race.stints_raw:
        num, first, last = (stint.get(k) for k in ("driver_number", "lap_start", "lap_end"))
        if None in (num, first, last):
            continue
        points = _clean_stint_laps(race, num, first, last, fuel_model=fuel_model)
        # A conflicting duplicate lap is not a second independent observation.
        per_lap = {}
        for lap, seconds in points:
            per_lap.setdefault(lap, set()).add(seconds)
        points = [(l, next(iter(v))) for l, v in sorted(per_lap.items()) if len(v) == 1]
        inputs.append({"driver": num, "stint": stint.get("stint_number"), "points": points})
        groups = []
        for point in points:
            if not groups or point[0] != groups[-1][-1][0] + 1:
                groups.append([])
            groups[-1].append(point)
        for group in groups:
            if len(group) < 2 * min_laps:
                continue
            slope = median(b[1] - a[1] for a, b in zip(group, group[1:]))
            residual = [(l, t - slope * l) for l, t in group]
            candidates = []
            for i in range(min_laps, len(group) - min_laps + 1):
                windows_compared += 1
                before = [t for _, t in residual[i-min_laps:i]]
                after = [t for _, t in residual[i:i+min_laps]]
                shift = median(after) - median(before)
                noise = median([abs(t - median(before)) for t in before] +
                               [abs(t - median(after)) for t in after])
                if abs(shift) >= max(threshold_s, 3 * noise):
                    candidates.append((abs(shift), i, shift, noise))
            selected = []
            for magnitude, i, shift, noise in sorted(candidates, reverse=True):
                if any(abs(i - j) < 2 * min_laps for j in selected):
                    continue
                selected.append(i)
                changes.append({"driver": race.abbr(num), "stint": stint.get("stint_number"),
                    "lap": group[i][0], "shift_s": round(shift, 3),
                    "direction": "slower" if shift > 0 else "faster",
                    "window_laps": min_laps, "noise_mad_s": round(noise, 3),
                    "kind": "observed_pace_shift", "cause": None})
    return jsonsafe({"changes": sorted(changes, key=lambda c: (c["lap"], c["driver"])),
        "status": "analysed" if windows_compared else "insufficient_data",
        "windows_compared": windows_compared,
        "uses_future_information": True, "fuel_model": _fuel_model(race, fuel_model),
        "evidence": evidence("adjacent_window_median_shift", inputs,
            sample_unit="lap within a contiguous clean stint", samples=sum(
                len(r["points"]) for r in inputs), kind="descriptive_detection",
            assumptions=[f"effect threshold {threshold_s} seconds; not a p-value",
                         f"{min_laps} laps on each side; three-MAD noise floor",
                         "median adjacent-lap trend removed; cause unobserved"],
            exclusions=["pit/neutralisation laps and missing-lap boundaries"])})
