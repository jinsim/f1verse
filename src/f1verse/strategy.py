"""Undercut / overcut verdicts — did the stop actually gain anything?

An undercut works when a driver pits first, runs fresh rubber while the
rival stays out, and emerges ahead. Whether it *worked* is a factual
question about the gap before and after the exchange, and this module
answers it with the circuit's real pit loss as the yardstick.
"""
from ._json import jsonsafe


def _gap_at(race, drv_num, lap):
    """Seconds behind the leader at a lap, from the interval feed if
    available, else derived from cumulative lap times."""
    laps = [l for l in race.laps if l["driver_number"] == drv_num
            and l["lap_number"] <= lap and l.get("lap_duration")]
    return sum(l["lap_duration"] for l in laps) if laps else None


def pit_exchanges(race, pit_loss_s: float | None = None,
                  window: int = 4) -> list:
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
        })
    return jsonsafe(sorted(out, key=lambda e: e["lap"]))
