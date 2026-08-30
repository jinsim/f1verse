"""Teammate head-to-head — the comparison fans ask for and cannot find.

Same car, same everything: the only clean controlled comparison in the
sport, and the one people search for by name ("f1 teammates h2h").
Qualifying and race are counted separately, as the community does.
"""
from ._json import jsonsafe
from .sources import openf1


def _rank(rows, key="position"):
    return {r["driver_number"]: r.get(key) for r in rows
            if r.get(key) is not None}


def head_to_head(year: int, upto_round: int | None = None) -> dict:
    """Season-long teammate scores, per constructor.

    Only rounds where both cars are classified count, so a retirement does
    not hand the other driver a free point.
    """
    meetings = sorted(openf1.get("meetings", year=year),
                      key=lambda m: m["date_start"])
    gps = [m for m in meetings if "test" not in m["meeting_name"].lower()
           and not m.get("is_cancelled")]
    if upto_round:
        gps = gps[:upto_round]

    score, names, teams = {}, {}, {}
    for m in gps:
        key = {"meeting_key": m["meeting_key"]}
        drivers = openf1.get("drivers", **key)
        by_team = {}
        for d in drivers:
            names[d["driver_number"]] = d.get("name_acronym")
            teams[d["driver_number"]] = d.get("team_name")
            by_team.setdefault(d.get("team_name"), set()).add(d["driver_number"])
        for label, session in (("quali", "Qualifying"), ("race", "Race")):
            ses = openf1.get("sessions", session_name=session, **key)
            if not ses:
                continue
            res = _rank(openf1.get("session_result",
                                   session_key=ses[0]["session_key"]))
            for team, nums in by_team.items():
                pair = sorted(n for n in nums if n in res)
                if len(pair) != 2:
                    continue
                a, b = pair
                win = a if res[a] < res[b] else b
                s = score.setdefault(team, {})
                s.setdefault(a, {"quali": 0, "race": 0})
                s.setdefault(b, {"quali": 0, "race": 0})
                s[win][label] += 1

    out = []
    for team, pair in score.items():
        rows = [{"abbr": names.get(n, n), "driver_number": n, **v}
                for n, v in pair.items()]
        rows.sort(key=lambda r: -(r["quali"] + r["race"]))
        out.append({"team": team, "drivers": rows})
    out.sort(key=lambda t: t["team"])
    return jsonsafe({"year": year, "rounds": len(gps), "teams": out})
