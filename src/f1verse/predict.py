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
