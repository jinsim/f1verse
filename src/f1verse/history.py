"""Careers, records and milestones — the "what does this mean historically"
layer that live timing cannot provide.

Backed by Jolpica (Ergast successor, 1950 → today).
"""
from collections import Counter

from ._json import jsonsafe
from .sources import jolpica


def _results(driver_id: str) -> list:
    return jolpica.paged(f"drivers/{driver_id}/results", "RaceTable", "Races")


def career(driver_id: str) -> dict:
    """Full career summary for a driver id (e.g. ``'max_verstappen'``)."""
    races = _results(driver_id)
    fin = [r["Results"][0] for r in races]
    pos = [int(f["position"]) for f in fin if f["position"].isdigit()]
    info = races[0]["Results"][0]["Driver"] if races else {}
    return jsonsafe({
        "driver": {"id": driver_id, "given": info.get("givenName"),
                   "family": info.get("familyName"),
                   "code": info.get("code"),
                   "born": info.get("dateOfBirth"),
                   "nationality": info.get("nationality")},
        "starts": len(races),
        "wins": sum(1 for p in pos if p == 1),
        "podiums": sum(1 for p in pos if p <= 3),
        "points_finishes": sum(1 for f in fin if float(f.get("points", 0)) > 0),
        "poles": sum(1 for f in fin if f.get("grid") == "1"),
        "dnfs": sum(1 for f in fin if not f["position"].isdigit()
                    or f.get("status", "").lower() not in ("finished",)
                    and not f.get("status", "").startswith("+")),
        "total_points": round(sum(float(f.get("points", 0)) for f in fin), 1),
        "best_finish": min(pos) if pos else None,
        "seasons": sorted({r["season"] for r in races}),
        "teams": [t for t, _ in Counter(
            f["Constructor"]["name"] for f in fin).most_common()],
    })


def milestones(driver_id: str, thresholds=(50, 100, 150, 200, 250, 300)) -> list:
    """Round numbers a driver is approaching — the "one win from N" hooks
    that make a race preview worth reading."""
    c = career(driver_id)
    out = []
    for label, value in (("starts", c["starts"]), ("wins", c["wins"]),
                         ("podiums", c["podiums"]), ("poles", c["poles"])):
        for t in thresholds:
            if 0 < t - value <= 3:
                out.append({"stat": label, "current": value, "target": t,
                            "remaining": t - value})
    return jsonsafe(out)


def circuit_history(circuit_id: str, last: int = 10) -> dict:
    """Winners, pole-to-win conversion and podium regulars at a circuit."""
    wins = jolpica.paged(f"circuits/{circuit_id}/results/1", "RaceTable", "Races")
    # qualifying rows use a different key than race results (Ergast schema)
    poles = {}
    for r in jolpica.paged(f"circuits/{circuit_id}/qualifying/1",
                           "RaceTable", "Races"):
        rows = r.get("QualifyingResults") or r.get("Results") or []
        if rows:
            poles[r["season"]] = rows[0]["Driver"]["driverId"]
    rows = []
    for r in wins[-last:]:
        w = r["Results"][0]
        rows.append({"season": r["season"], "race": r["raceName"],
                     "winner": w["Driver"]["familyName"],
                     "winner_id": w["Driver"]["driverId"],
                     "constructor": w["Constructor"]["name"],
                     "from_grid": int(w["grid"]) if w["grid"].isdigit() else None,
                     "from_pole": poles.get(r["season"]) == w["Driver"]["driverId"]})
    conv = [r for r in rows if r["from_pole"] is not None]
    return jsonsafe({
        "circuit_id": circuit_id,
        "races_held": len(wins),
        "recent": rows,
        "pole_to_win_rate": (round(sum(r["from_pole"] for r in conv) / len(conv), 3)
                             if conv else None),
        "most_wins": Counter(r["Results"][0]["Driver"]["familyName"]
                             for r in wins).most_common(5),
    })


def standings(year: int, kind: str = "driver") -> list:
    """Championship standings after the latest completed round."""
    tbl = "DriverStandings" if kind == "driver" else "ConstructorStandings"
    d = jolpica.get(f"{year}/{kind}Standings")
    lists = d["StandingsTable"]["StandingsLists"]
    if not lists:
        return []
    rows = []
    for s in lists[0][tbl]:
        who = s["Driver"] if kind == "driver" else s["Constructor"]
        rows.append({"position": int(s["position"]),
                     "name": who.get("code") or who.get("name"),
                     "full_name": (f"{who.get('givenName','')} "
                                   f"{who.get('familyName','')}".strip()
                                   or who.get("name")),
                     "points": float(s["points"]), "wins": int(s["wins"])})
    return jsonsafe({"round": int(lists[0]["round"]), "standings": rows})
