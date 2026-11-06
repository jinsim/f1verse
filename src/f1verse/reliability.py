# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Observed all-cause retirement survival, with completed races censored."""
from ._evidence import evidence
from ._json import jsonsafe


def retirement_risk(races) -> dict:
    """Kaplan-Meier survival over completed native race starts.

    Mechanical failure and accidents are not separable from a DNF flag.
    This describes supplied races, not a driver's future reliability or
    physical tyre life. Race starts are dependent within each race.
    """
    observations, skipped, seen = [], [], set()
    for race in races:
        identity = (race.year, race.round, race.name)
        if identity in seen:
            continue
        seen.add(identity)
        if race.lifecycle not in ("settled", "final"):
            skipped.append({"session": identity, "reason": "session is not settled"})
            continue
        for row in race.result:
            num = row.get("driver_number")
            # DNS and DSQ are not observed mechanical/accident retirements.
            if row.get("dns") or row.get("dsq"):
                skipped.append({"session": identity, "driver_number": num,
                                "reason": "DNS or DSQ"})
                continue
            laps = row.get("number_of_laps")
            if (num is None or not isinstance(row.get("dnf"), bool) or not isinstance(laps, int)
                    or isinstance(laps, bool) or laps < 0):
                skipped.append({"session": identity, "driver_number": num,
                                "reason": "missing retirement flag or lap exposure"})
                continue
            observations.append({"session": identity, "driver": race.abbr(num),
                                 "completed_laps": laps, "event": bool(row["dnf"])})
    survival, curve = 1.0, []
    for lap in sorted({o["completed_laps"] for o in observations}):
        at_risk = sum(o["completed_laps"] >= lap for o in observations)
        events = sum(o["completed_laps"] == lap and o["event"] for o in observations)
        censored = sum(o["completed_laps"] == lap and not o["event"] for o in observations)
        survival *= 1 - events / at_risk
        curve.append({"completed_laps": lap, "at_risk": at_risk, "retirements": events,
                      "censored": censored, "survival": round(survival, 6)})
    return jsonsafe({"curve": curve, "starts": len(observations), "skipped": skipped,
        "available": bool(observations),
        "reason": None if observations else "no usable settled race starts",
        "coverage": {"cause": "all-cause DNF; accident versus mechanical not identified",
                     "time_resolution": "completed laps; no exact failure time",
                     "independent_units": "races; starts within a race are dependent"},
        "evidence": evidence("kaplan_meier", observations,
            sample_unit="race start", samples=len(observations), kind="descriptive_estimate",
            assumptions=["independent administrative censoring within supplied sample",
                         "comparable race distances and conditions are not guaranteed",
                         "not a causal effect or a calibrated future failure probability"])})
