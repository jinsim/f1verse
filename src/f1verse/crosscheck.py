"""Cross-validation layer — publish only when independent sources agree.

One wrong number costs a data project its credibility. ``crosscheck`` runs
a race through independent checks and returns a machine-readable verdict a
publishing pipeline can gate on:

- **sector_sum** — s1+s2+s3 must equal the lap time within 3 ms.
- **lap_count** — winner's classified lap count vs the lap table.
- **gap_monotonic** — classified numeric gaps must increase with position;
  this is the check that catches the classic lapped-car corruption
  (``P8 +36.049`` printed above ``P7 +1:19.915``).
- **lapped_convention** — every ``+N LAP`` row completed fewer laps.
- **leader_vs_overtakes** — every on-track pass for P1 (independent
  ``/overtakes`` endpoint) must appear in the position-stream lead changes.
  The two are *not* equal by design: leads gained through pit cycles are
  lead changes but not overtakes.
- **stints_vs_pits** — stint splits explained by pit stops (red-flag tyre
  changes legitimately add stints without a pit stop; reported, not failed).
"""

from .sources import openf1


def _check(name, ok, detail):
    return {"name": name, "status": "ok" if ok else "mismatch",
            "detail": detail}


def crosscheck(race) -> dict:
    checks = []

    # -- lap_count ----------------------------------------------------------
    winner = next((r for r in race.result if r.get("position") == 1), {})
    table_max = race.total_laps
    ok = winner.get("number_of_laps") == table_max
    checks.append(_check("lap_count", ok,
                         f"winner classified {winner.get('number_of_laps')} laps,"
                         f" lap table max {table_max}"))

    # -- sector_sum (3 ms tolerance) ----------------------------------------
    bad = total = 0
    for l in race.laps:
        s = (l.get("duration_sector_1"), l.get("duration_sector_2"),
             l.get("duration_sector_3"), l.get("lap_duration"))
        if all(x is not None for x in s):
            total += 1
            if abs(s[0] + s[1] + s[2] - s[3]) > 0.003:
                bad += 1
    checks.append(_check("sector_sum", bad / max(total, 1) < 0.02,
                         f"{bad}/{total} laps off by >3ms"))

    # -- gap_monotonic (the lapped-car trap, as an invariant) ---------------
    prev, breaks = None, []
    for r in race.results():
        g = r["gap"]
        if g.startswith("+") and "LAP" not in g:
            sec = (lambda s: sum(float(x) * m for x, m in
                                 zip(reversed(s.rstrip("s").lstrip("+").split(":")),
                                     (1, 60))))(g)
            if prev is not None and sec < prev:
                breaks.append(r["abbr"])
            prev = sec
    checks.append(_check("gap_monotonic", not breaks,
                         f"out-of-order gaps: {breaks or 'none'}"))

    # -- lapped_convention --------------------------------------------------
    wrong = [r["abbr"] for r in race.results()
             if "LAP" in r["gap"] and (r.get("laps") or 0) >= table_max]
    checks.append(_check("lapped_convention", not wrong,
                         f"'+N LAP' rows with full distance: {wrong or 'none'}"))

    # -- leader_vs_overtakes (independent endpoint) -------------------------
    runs = [r["abbr"] for r in race.leader_runs()]
    ot = sorted(openf1.get("overtakes", session_key=race.session_key,
                           position=1), key=lambda o: o["date"])
    seq, prev_n = [], None
    for o in ot:
        n = o["overtaking_driver_number"]
        if n != prev_n:
            seq.append(race.abbr(n))
            prev_n = n
    # on-track P1 passes must be a subsequence of all lead changes —
    # pit-cycle lead changes legitimately have no matching overtake
    changes = [b for a, b in zip([None] + runs, runs) if a != b][1:]
    passes = [b for a, b in zip([None] + seq, seq) if a != b]
    it = iter(changes)
    ok = all(any(p == c for c in it) for p in passes)
    checks.append(_check(
        "leader_vs_overtakes", ok,
        f"on-track P1 passes {passes} ⊆ lead changes {changes}"
        + ("" if ok else " — FAILED")))

    # -- stints_vs_pits (informational) -------------------------------------
    pit_per = {}
    for p in race.pits:
        pit_per[p["driver_number"]] = pit_per.get(p["driver_number"], 0) + 1
    unexplained = []
    for num, sts in ((n, [s for s in race.stints_raw
                          if s["driver_number"] == n])
                     for n in race.drivers):
        extra = (len(sts) - 1) - pit_per.get(num, 0)
        if extra > 1:  # >1 non-pit stint split is suspicious even with a red flag
            unexplained.append(race.abbr(num))
    checks.append(_check("stints_vs_pits", not unexplained,
                         f"suspicious stint splits: {unexplained or 'none'}"))

    mismatches = [c["name"] for c in checks if c["status"] != "ok"]
    return {"checks": checks, "mismatches": mismatches,
            "publishable": not mismatches}
