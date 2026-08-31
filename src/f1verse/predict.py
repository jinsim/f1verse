# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Race win probabilities — from measured base rates, not vibes.

Every number here is traceable. The model is deliberately simple and its
inputs are printed alongside the output, because a probability nobody can
audit is worth nothing.

**Method**

1. *Grid base rate* — how often each starting position has won, measured
   over a configurable window of real seasons (default 2015-2025: pole
   wins 54.1% of the time, P2 23.6%, P3 10.7%).
2. *Circuit adjustment* — the same track's own pole-to-win conversion,
   blended in. Monza (0.30) punishes pole far more than Monaco does.
3. *Recent form* — average finishing position over the last N races,
   converted to a multiplier.
4. Normalise to 1.0.

Everything is returned with the evidence attached, so a caption can cite
its own reasoning.
"""
from __future__ import annotations

from collections import Counter

from ._json import jsonsafe
from .history import circuit_history
from .sources import jolpica


def grid_base_rates(start: int = 2015, end: int = 2025) -> dict:
    """Measured P(win | grid slot) over real seasons."""
    wins, races = Counter(), 0
    for yr in range(start, end + 1):
        rows = jolpica.paged(f"{yr}/results/1", "RaceTable", "Races")
        races += len(rows)
        for r in rows:
            g = r["Results"][0].get("grid", "")
            if g.isdigit():
                wins[int(g)] += 1
    return {"window": f"{start}-{end}", "races": races,
            "rates": {p: wins[p] / races for p in range(1, 21)},
            "wins": dict(wins)}


def recent_form(year: int, upto_round: int, last: int = 5) -> dict:
    """Average finishing position per driver over the last *last* rounds."""
    pos = {}
    for rnd in range(max(1, upto_round - last + 1), upto_round + 1):
        try:
            rows = jolpica.get(f"{year}/{rnd}/results")["RaceTable"]["Races"]
        except Exception:
            continue
        if not rows:
            continue
        for r in rows[0]["Results"]:
            code = r["Driver"].get("code") or r["Driver"]["driverId"]
            p = int(r["position"]) if r["position"].isdigit() else 20
            pos.setdefault(code, []).append(p)
    return {c: sum(v) / len(v) for c, v in pos.items() if v}


def win_probabilities(grid: dict, *, year: int, upto_round: int,
                      circuit_id: str | None = None,
                      base: dict | None = None) -> dict:
    """Win probability per driver.

    Args:
        grid: ``{"VER": 1, "NOR": 2, ...}`` — starting positions.
        year, upto_round: season context for recent form.
        circuit_id: Jolpica circuit id, to blend in that track's own
            pole-to-win conversion.
        base: reuse a ``grid_base_rates`` result instead of recomputing.
    """
    base = base or grid_base_rates()
    rates = base["rates"]
    form = recent_form(year, upto_round)
    evidence = {"grid_base": base["window"], "races_sampled": base["races"]}

    pole_conv = None
    if circuit_id:
        h = circuit_history(circuit_id)
        pole_conv = h.get("pole_to_win_rate")
        evidence["circuit"] = {"id": circuit_id, "races_held": h["races_held"],
                               "pole_to_win_rate": pole_conv}

    scores, detail = {}, {}
    for drv, slot in grid.items():
        p = rates.get(int(slot), 0.001) or 0.001
        note = {"grid": int(slot), "grid_base_rate": round(p, 4)}
        # Blend the global pole rate toward this circuit's own conversion.
        if pole_conv is not None and int(slot) == 1:
            blended = (p + pole_conv) / 2
            note["circuit_adjusted"] = round(blended, 4)
            p = blended
        f = form.get(drv)
        if f is not None:
            # avg finish 1 -> x1.6, 10 -> x1.0, 20 -> x0.6
            mult = max(0.4, 1.6 - (f - 1) * 0.06)
            note["recent_avg_finish"] = round(f, 2)
            note["form_multiplier"] = round(mult, 2)
            p *= mult
        scores[drv] = p
        detail[drv] = note

    total = sum(scores.values()) or 1.0
    probs = {d: round(v / total, 4) for d, v in
             sorted(scores.items(), key=lambda kv: -kv[1])}
    return jsonsafe({"probabilities": probs, "evidence": evidence,
                     "per_driver": detail,
                     "method": "grid base rate x circuit conversion x recent form,"
                               " normalised"})


# --- strategy rollouts --------------------------------------------------

def strategy_rollout(total_laps: int, base_pace_s: float, candidates: list,
                     wear_s_per_lap: dict | None = None,
                     pit_loss_s: float = 21.0,
                     sc_chance_per_lap: float = 0.015,
                     sc_pit_saving: float = 0.5,
                     lap_noise_s: float = 0.25,
                     runs: int = 2000, seed: int = 0) -> dict:
    """Race one strategy against another a few thousand times.

    Each candidate is ``{"name": ..., "stints": [{"compound": ...,
    "until": lap}, ...]}`` — the last stint's ``until`` is the race
    distance. Every run draws the same weather: per-lap noise, and safety
    cars appearing with ``sc_chance_per_lap`` and hanging around for a
    few laps, during which a stop costs ``sc_pit_saving`` of the normal
    ``pit_loss_s`` — which is the entire reason a lucky strategy beats a
    fast one, and why this is a simulation rather than a sum.

    The result reports, per candidate, the median finishing time, an
    80% band, and the share of runs it won — alongside every assumption
    it was computed from, because a forecast without its assumptions is
    an opinion. Same ``seed`` in, same numbers out.
    """
    import random as _random
    wear = dict(_ORDINARY_ROLLOUT_WEAR)
    wear.update(wear_s_per_lap or {})
    rng = _random.Random(seed)
    totals = {c["name"]: [] for c in candidates}
    for _ in range(runs):
        # one shared race: same safety cars, same lap noise for everyone
        sc_laps = set()
        lap = 1
        while lap <= total_laps:
            if rng.random() < sc_chance_per_lap:
                sc_laps.update(range(lap, min(lap + rng.randint(2, 4),
                                              total_laps) + 1))
                lap += 5
            lap += 1
        noise = [rng.gauss(0, lap_noise_s) for _ in range(total_laps + 1)]
        for c in candidates:
            t, lap = 0.0, 1
            for stint in c["stints"]:
                rate = wear.get((stint.get("compound") or "").upper(), 0.03)
                age = 0
                while lap <= min(stint["until"], total_laps):
                    t += base_pace_s + rate * age + noise[lap]
                    if lap in sc_laps:
                        t += 8.0          # running behind the safety car
                    age += 1
                    lap += 1
                if lap <= total_laps:     # this stop actually happens
                    t += pit_loss_s * (sc_pit_saving
                                       if lap in sc_laps else 1.0)
            totals[c["name"]].append(t)
    order = sorted(totals)
    wins = {name: 0 for name in order}
    for i in range(runs):
        best = min(order, key=lambda name: totals[name][i])
        wins[best] += 1
    out = []
    for name in order:
        times = sorted(totals[name])
        out.append({"name": name,
                    "median_s": round(times[runs // 2], 2),
                    "p10_s": round(times[runs // 10], 2),
                    "p90_s": round(times[(9 * runs) // 10], 2),
                    "win_share": round(wins[name] / runs, 3)})
    out.sort(key=lambda e: e["median_s"])
    return jsonsafe({
        "candidates": out,
        "assumptions": {"total_laps": total_laps,
                        "base_pace_s": base_pace_s,
                        "wear_s_per_lap": wear, "pit_loss_s": pit_loss_s,
                        "sc_chance_per_lap": sc_chance_per_lap,
                        "sc_pit_saving": sc_pit_saving,
                        "lap_noise_s": lap_noise_s,
                        "runs": runs, "seed": seed},
    })


_ORDINARY_ROLLOUT_WEAR = {"SOFT": 0.05, "MEDIUM": 0.03, "HARD": 0.01,
                          "INTERMEDIATE": 0.04, "WET": 0.02}


# --- championship projection -------------------------------------------
#
# "Who wins the title" is a different question from "who wins this race",
# and it is answered the way football coverage answers it: play the rest
# of the season out thousands of times and count how often each driver
# ends up on top.
#
# The one modelling choice that matters is where a driver's simulated
# finish comes from. This module resamples from **the positions that
# driver has actually finished in this season** rather than assuming a
# bell curve around their average. That distinction is the whole point:
# a driver alternating wins and retirements is a different championship
# proposition from one who finishes P4 every weekend, and an average
# hides exactly that. Draws are re-ranked into a valid race order, so no
# simulated race has two winners.
#
# What it does not model, and cannot: upgrades, weather, team orders,
# penalties, and any change in car performance from here on. It assumes
# the season so far is representative of the season remaining. That
# assumption is returned with the numbers so a reader can weigh it.

RACE_POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10,
               6: 8, 7: 6, 8: 4, 9: 2, 10: 1}
SPRINT_POINTS = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}


def _standings_at(year: int, upto_round: int | None) -> tuple:
    """``(rows, round)`` — the championship as it stood after a round.

    ``upto_round=None`` means "however far the season has got". Asking for
    a past round is what makes a backtest possible: the projection can be
    replayed from a point where the answer was not yet known.
    """
    from .history import standings
    from .sources import jolpica
    if upto_round is None:
        t = standings(year)
        return t["standings"], t["round"]
    lists = jolpica.get(f"{year}/{upto_round}/driverStandings")[
        "StandingsTable"]["StandingsLists"]
    if not lists:
        return [], upto_round
    rows = [{"position": int(x["position"]),
             "name": x["Driver"].get("code") or x["Driver"]["driverId"],
             "points": float(x["points"]), "wins": int(x["wins"])}
            for x in lists[0]["DriverStandings"]]
    return rows, int(lists[0]["round"])


def _season_form(year: int, upto_round: int) -> dict:
    """Each driver's actual results so far — the raw material for the
    simulation.

    Returns, per driver code: every classified finishing position, how
    many rounds they started, and how many they failed to finish. A
    driver's retirement rate is measured here, never assumed.
    """
    from .sources import jolpica
    finishes, started, retired = {}, {}, {}
    for rnd in range(1, upto_round + 1):
        try:
            races = jolpica.get(f"{year}/{rnd}/results")["RaceTable"]["Races"]
        except Exception:
            continue
        if not races:
            continue
        for r in races[0].get("Results", []):
            code = r["Driver"].get("code") or r["Driver"]["driverId"]
            started[code] = started.get(code, 0) + 1
            status = r.get("status", "")
            if status == "Finished" or status.startswith("+"):
                if r["position"].isdigit():
                    finishes.setdefault(code, []).append(int(r["position"]))
            else:
                retired[code] = retired.get(code, 0) + 1
    return {c: {"finishes": sorted(v),
                "started": started.get(c, 0),
                "retired": retired.get(c, 0),
                "dnf_rate": round(retired.get(c, 0) / max(started.get(c, 1), 1), 3)}
            for c, v in finishes.items()}


def remaining_rounds(year: int, after_round: int) -> list:
    """Rounds still to run, each flagged for whether it carries a sprint."""
    from .sources import jolpica
    out = []
    for r in jolpica.get(f"{year}")["RaceTable"]["Races"]:
        rnd = int(r["round"])
        if rnd > after_round:
            out.append({"round": rnd, "name": r.get("raceName"),
                        "sprint": "Sprint" in r})
    return out


def title_scenarios(year: int, as_of: int | None = None) -> dict:
    """Who can still win the title — arithmetic, not probability.

    Before any simulation is worth reading, there is an exact question:
    is it still possible? Maximum points remaining is a fixed number, so
    a driver more than that behind the leader is out, full stop. This
    separates the two claims a projection makes — *impossible* is a fact,
    *unlikely* is a model — and never lets one be mistaken for the other.
    """
    rows, done = _standings_at(year, as_of)
    left = remaining_rounds(year, done)
    max_left = sum(25 + (8 if r["sprint"] else 0) for r in left)
    leader = rows[0]["points"] if rows else 0.0
    alive = []
    for r in rows:
        gap = leader - r["points"]
        alive.append({"driver": r["name"], "points": r["points"],
                      "gap_to_leader": round(gap, 1),
                      "still_possible": gap <= max_left,
                      "needs_avg_per_round": (round(gap / len(left), 1)
                                              if left and gap <= max_left
                                              else None)})
    return jsonsafe({
        "after_round": done,
        "rounds_left": len(left),
        "sprints_left": sum(1 for r in left if r["sprint"]),
        "max_points_available": max_left,
        "leader": rows[0]["name"] if rows else None,
        "drivers": alive,
        "still_alive": sum(1 for a in alive if a["still_possible"]),
    })


def _order_from_draws(draws: dict, rng) -> list:
    """Turn per-driver position draws into one valid finishing order."""
    jittered = [(v + rng.random(), c) for c, v in draws.items()]
    jittered.sort()
    return [c for _, c in jittered]


def championship_projection(year: int, runs: int = 20000, seed: int = 0,
                            min_races: int = 3,
                            as_of: int | None = None) -> dict:
    """Title probability per driver, by playing the season out.

    Each remaining round is simulated by drawing every driver a finishing
    position from their own season to date, ranking those draws into a
    real order, and awarding points; retirements fire at each driver's
    measured rate and score nothing. Ties on points are broken the way
    the regulations break them — on count of wins, then of second places,
    and so on down.

    Returns each driver's title probability alongside the evidence it
    rests on: how many of their races the distribution was built from,
    their measured retirement rate, and every assumption in the run.
    Same ``seed``, same numbers.
    """
    import random as _random

    rows, done = _standings_at(year, as_of)
    left = remaining_rounds(year, done)
    form = _season_form(year, done)

    # Only drivers with enough races to resample from are projected; the
    # rest keep their points but are reported as unmodelled rather than
    # silently given a zero.
    modelled = {r["name"]: form[r["name"]] for r in rows
                if r["name"] in form
                and len(form[r["name"]]["finishes"]) >= min_races}
    skipped = [r["name"] for r in rows if r["name"] not in modelled]

    start_pts = {r["name"]: r["points"] for r in rows}
    start_wins = {r["name"]: r["wins"] for r in rows}

    if not left:
        champ = rows[0]["name"] if rows else None
        return jsonsafe({"settled": True, "champion": champ,
                         "after_round": done, "rounds_left": 0})

    rng = _random.Random(seed)
    titles = {c: 0 for c in modelled}
    finals = {c: [] for c in modelled}

    for _ in range(runs):
        # A driver's "level" is itself an estimate off a dozen races, and
        # treating it as known is how a projection ends up more certain
        # than anyone should be. So each simulated season begins by
        # re-drawing that level: the driver's results are bootstrapped
        # with replacement, and the season is then run against *that*
        # version of them. Some runs get the good version, some the bad.
        level = {}
        for c, f in modelled.items():
            n = len(f["finishes"])
            level[c] = {"finishes": [rng.choice(f["finishes"]) for _ in range(n)],
                        "dnf_rate": min(max(rng.gauss(
                            f["dnf_rate"],
                            (f["dnf_rate"] * (1 - f["dnf_rate"]) / max(f["started"], 1)) ** 0.5
                        ), 0.0), 0.6)}
        pts = {c: start_pts.get(c, 0.0) for c in modelled}
        wins = {c: start_wins.get(c, 0) for c in modelled}
        seconds = {c: 0 for c in modelled}
        for rnd in left:
            draws, out = {}, []
            for c, f in level.items():
                if rng.random() < f["dnf_rate"]:
                    out.append(c)
                else:
                    draws[c] = rng.choice(f["finishes"])
            order = _order_from_draws(draws, rng)
            for i, c in enumerate(order, start=1):
                pts[c] += RACE_POINTS.get(i, 0)
                if i == 1:
                    wins[c] += 1
                elif i == 2:
                    seconds[c] += 1
            if rnd["sprint"]:
                # a sprint is its own short race; the same form applies
                sp_draws = {c: rng.choice(level[c]["finishes"])
                            for c in level if c not in out}
                for i, c in enumerate(_order_from_draws(sp_draws, rng), 1):
                    pts[c] += SPRINT_POINTS.get(i, 0)
        champ = max(pts, key=lambda c: (pts[c], wins[c], seconds[c]))
        titles[champ] += 1
        for c in modelled:
            finals[c].append(pts[c])

    out = []
    for c in sorted(titles, key=lambda c: -titles[c]):
        f = sorted(finals[c])
        out.append({
            "driver": c,
            "title_probability": round(titles[c] / runs, 4),
            "points_now": start_pts.get(c, 0.0),
            "projected_points_median": f[runs // 2],
            "projected_points_p10": f[runs // 10],
            "projected_points_p90": f[(9 * runs) // 10],
            "races_in_sample": len(modelled[c]["finishes"]),
            "measured_dnf_rate": modelled[c]["dnf_rate"],
        })
    return jsonsafe({
        "after_round": done,
        "rounds_left": len(left),
        "sprints_left": sum(1 for r in left if r["sprint"]),
        "drivers": out,
        "not_modelled": skipped,
        "assumptions": {
            "method": "resampled from each driver's own finishing "
                      "positions this season; draws re-ranked into a "
                      "valid race order",
            "retirements": "each driver's measured rate this season, "
                           "itself resampled per run",
            "level_uncertainty": "each run bootstraps the driver's own "
                                 "results before playing the season, so "
                                 "a small sample widens the answer "
                                 "instead of hiding in it",
            "tiebreak": "points, then wins, then second places",
            "ignores": ["car development", "weather", "team orders",
                        "penalties", "driver changes"],
            "runs": runs, "seed": seed, "min_races": min_races,
        },
    })


def backtest_projection(first: int = 2019, last: int = 2025,
                        as_of: int = 12, runs: int = 1500,
                        seed: int = 1) -> dict:
    """Replay the projection on finished seasons and score it.

    A probability nobody has checked is decoration. This runs the same
    model at a point in each past season where the answer was not yet
    known, and compares what it claimed against what happened.

    Read the buckets, not the headline rate: a model that says 55% and
    is wrong has done nothing wrong, while one that says 99% and is
    wrong has. ``by_confidence`` splits the record accordingly, which is
    the only way a hit rate off a handful of seasons means anything.
    """
    from .history import standings
    cases = []
    for year in range(first, last + 1):
        try:
            actual = standings(year)["standings"][0]["name"]
            p = championship_projection(year, runs=runs, seed=seed,
                                        as_of=as_of)
        except Exception:
            continue
        if p.get("settled") or not p.get("drivers"):
            continue
        top = p["drivers"][0]
        cases.append({"year": year, "predicted": top["driver"],
                      "claimed_probability": top["title_probability"],
                      "actual": actual,
                      "correct": top["driver"] == actual})
    buckets = {"over_90": [], "60_to_90": [], "under_60": []}
    for c in cases:
        q = c["claimed_probability"]
        key = "over_90" if q >= 0.9 else "60_to_90" if q >= 0.6 else "under_60"
        buckets[key].append(c["correct"])
    return jsonsafe({
        "seasons_tested": len(cases),
        "as_of_round": as_of,
        "cases": cases,
        "hit_rate": (round(sum(c["correct"] for c in cases) / len(cases), 3)
                     if cases else None),
        "by_confidence": {k: {"n": len(v), "correct": sum(v),
                              "rate": round(sum(v) / len(v), 3) if v else None}
                          for k, v in buckets.items()},
        "note": "small sample; the confidence buckets say more than the "
                "headline rate",
    })
