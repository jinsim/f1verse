# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Lap-resolved events with stable identity and explicit evidence.

These are observations and candidate turning points, not causal effects.
No archive or media is fetched to build them.
"""
from ._evidence import digest, evidence
from ._json import jsonsafe


def _stamp(race, rows):
    session = {"year": getattr(race, "year", None),
               "round": getattr(race, "round", None),
               "session": getattr(race, "name", None),
               "session_key": getattr(race, "session_key", None)}
    groups = {}
    for row in rows:
        identity = {**session, **{k: row.get(k) for k in
                    ("kind", "lap", "abbr", "over", "rival", "stint")}}
        key = digest(identity)[:24]
        version = digest(row)
        groups.setdefault(key, {})[version] = row
    out = []
    prov = race.provenance() if hasattr(race, "info") else {}
    for key, versions in groups.items():
        # Conflicting versions are exposed instead of depending on arrival order.
        ordered = sorted(versions)
        row = dict(versions[ordered[-1]])
        default = (["position", "laps"] if row["kind"] == "lead" else
                   ["race_control"] if row["kind"] in ("red", "sc") else
                   ["laps", "session_result"])
        endpoints = row.pop("_endpoints", default)
        refs = [{"endpoint": ep, "sha256": prov.get(ep, {}).get("sha256"),
                 "fetched_at": prov.get(ep, {}).get("fetched_at")}
                for ep in endpoints]
        stamps = [r["fetched_at"] for r in refs if r["fetched_at"]]
        row.update({"event_id": key, "revision": ordered[-1],
                    "kind_of_claim": "observed" if len(ordered) == 1 else "conflicting",
                    "resolution": "lap",
                    "observed_at": max(stamps) if stamps else None,
                    "occurred_at": row.get("occurred_at"),
                    "evidence": refs, "conflicting_revisions": ordered
                    if len(ordered) > 1 else [],
                    "alternatives": [{"revision": rev, "event": versions[rev]}
                                     for rev in ordered] if len(ordered) > 1 else []})
        out.append(row)
    return jsonsafe(sorted(out, key=lambda r: (r["lap"], r["kind"], r["event_id"])))


def race_events(race) -> dict:
    """Timeline, pit stops and observed pit exchanges, with evidence links."""
    from .strategy import pit_exchanges
    rows = [{k: v for k, v in r.items() if k in
             ("lap", "kind", "abbr", "over", "title")} for r in race.timeline()]
    for row in rows:
        row["_endpoints"] = (["position", "laps"] if row["kind"] == "lead"
                              else ["race_control"] if row["kind"] in ("red", "sc")
                              else ["session_result", "laps"])
    for pit in race.pits:
        rows.append({"lap": pit["lap_number"], "kind": "pit",
                     "abbr": race.abbr(pit["driver_number"]),
                     "occurred_at": pit.get("date"),
                     "title": f"{race.abbr(pit['driver_number'])} pits",
                     "_endpoints": ["pit"]})
    for exchange in pit_exchanges(race, resolve_pit_loss=False):
        rows.append({"lap": exchange["lap"], "kind": "pit_exchange",
                     "abbr": exchange["driver"], "rival": exchange["rival"],
                     "title": "Observed gap change across a pit cycle",
                     "gain_s": exchange["gain_s"],
                     "rival_pitted_lap": exchange["rival_pitted_lap"],
                     "causal_effect": None,
                     "_endpoints": ["laps", "pit", "race_control"]})
    events = _stamp(race, rows)
    return jsonsafe({"schema_version": 1, "events": events,
                     "availability": race.availability(),
                     "evidence": evidence("lap_events", {
                         "session": getattr(race, "session_key", None),
                         "laps": race.laps, "pits": race.pits,
                         "race_control": race.race_control,
                         "position": race._p1, "results": race.result},
                         sample_unit="event", samples=len(events), kind="observed",
                         assumptions=["lap-resolved observations; event order within a lap unknown",
                                      "gap changes do not identify causal strategy effects"])})


def turning_points(race, limit: int = 10) -> dict:
    """Rank observed race changes; the score is a heuristic, not a probability."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")
    report = race_events(race)
    weights = {"red": 5, "sc": 4, "lead": 3, "out": 2,
               "pit_exchange": 2, "pit": 1}
    candidates = []
    for row in report["events"]:
        candidates.append({**row, "importance_score": weights[row["kind"]],
                           "score_kind": "editorial_heuristic",
                           "causal_effect": None})
    report["events"] = sorted(candidates, key=lambda r: (
        -r["importance_score"], r["lap"], r["event_id"]))[:limit]
    report["ranking"] = {"method": "fixed event-kind priority", "weights": weights,
                          "uses_future_information": True,
                          "note": "retrospective candidates, not live predictions or win value"}
    return jsonsafe(report)
