"""Data quality — how complete, how old, how settled, and what changed.

``crosscheck`` answers *do independent sources agree*. That is a verdict,
not an explanation, and it is silent about three things a publisher needs
to know before putting a number on screen:

- **completeness** — a race with 3% of its sector times missing passes
  every agreement check, because the rows that are absent cannot disagree
  with anything.
- **age** — the answer came from a cache. From how long ago?
- **lifecycle** — the chequered flag is not the final classification.
  A result inside the stewards' window is provisional, and one that has
  been rewritten since it was first seen is *corrected*.

:func:`quality_report` composes all four into one machine-readable dict a
pipeline can gate on and a correction notice can be written from.

:func:`snapshot` and :func:`diff` are the pieces for keeping a record of
corrections. Deliberately, ``snapshot`` has no ``as_of`` parameter: this
library can hand back the classification as it stands now, and can tell
you when it saw that change — it cannot reconstruct a value nobody here
ever fetched. Persisting snapshots is the caller's job; what f1verse
guarantees is that they are normalised, hashed and comparable.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from ._json import jsonsafe
from .session import SCHEMA_VERSION

_MISSING_LIMIT = 50   # enumerate this many gaps, then just count them

# Fields the classification itself is built from. Only these gate
# publication: a race is not unpublishable because out-laps carry no
# sector times — that is normal, and in qualifying it is most of a
# session. Detail fields are reported and warned about instead.
_CORE = ("laps", "lap_time", "position_stream")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _digest(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   default=str).encode()).hexdigest()


# -- completeness -----------------------------------------------------------

def _coverage(race) -> tuple:
    """Field-level completeness plus a bounded list of the actual gaps.

    Lap rows are counted per driver against that driver's classified lap
    count, capped at it: a car that retires mid-lap leaves a partial row
    the classification does not count, and letting those spill over would
    push "completeness" above 1.0 and hide a real gap elsewhere.
    """
    classified = {r["driver_number"]: r for r in race.result}
    rows_per = {}
    for l in race.laps:
        rows_per[l["driver_number"]] = rows_per.get(l["driver_number"], 0) + 1
    expected = present = 0
    for num, r in classified.items():
        want = r.get("number_of_laps") or 0
        expected += want
        present += min(rows_per.get(num, 0), want)

    timed = timed_ok = sect = sect_ok = 0
    gaps = {"lap_duration": [], "sector": []}
    counts = {"lap_duration": 0, "sector": 0}
    for l in race.laps:
        if l["lap_number"] <= 1:
            continue        # no lap time for the standing start
        timed += 1
        if l.get("lap_duration") is not None:
            timed_ok += 1
        else:
            counts["lap_duration"] += 1
            if len(gaps["lap_duration"]) < _MISSING_LIMIT:
                gaps["lap_duration"].append(
                    f"{race.abbr(l['driver_number'])}"
                    f".lap_{l['lap_number']}.lap_duration")
        for i in (1, 2, 3):
            sect += 1
            if l.get(f"duration_sector_{i}") is not None:
                sect_ok += 1
            else:
                counts["sector"] += 1
                if len(gaps["sector"]) < _MISSING_LIMIT:
                    gaps["sector"].append(
                        f"{race.abbr(l['driver_number'])}"
                        f".lap_{l['lap_number']}.sector_{i}")

    stints = race.stints_raw
    comp_ok = sum(1 for s in stints if s.get("compound"))
    counts["compound"] = len(stints) - comp_ok

    ratio = lambda a, b: round(a / b, 4) if b else None
    cov = {"laps": ratio(present, expected),
           "lap_time": ratio(timed_ok, timed),
           "sectors": ratio(sect_ok, sect),
           "compound": ratio(comp_ok, len(stints))}
    if race.KIND == "Race":
        # only a race is scored on the leader stream — in qualifying,
        # "who held P1" is an artefact of run plans, not a fact to check
        cov["position_stream"] = 1.0 if race._p1 else 0.0
    core = [cov[k] for k in _CORE if cov.get(k) is not None]
    cov["overall"] = round(min(core), 4) if core else None
    # rarest gaps first: a missing lap time matters more than a sector
    missing = gaps["lap_duration"] + gaps["sector"]
    return cov, missing[:_MISSING_LIMIT], counts, {
        "expected_laps": expected, "present_laps": present,
        "stints": len(stints)}


# -- report -----------------------------------------------------------------

def quality_report(race) -> dict:
    """Structured trust report for a loaded session.

    ``state`` is the headline: ``provisional`` (do not publish yet),
    ``settled``, ``final``, or ``corrected`` — the last overriding the
    others whenever a revision to this session's rows has been observed.
    ``publishable`` is the conjunction a pipeline should gate on.
    """
    cov, missing, gap_counts, counts = _coverage(race)
    prov = race.provenance()
    revs = race.revisions()
    lifecycle = race.lifecycle
    state = "corrected" if revs else lifecycle

    ages = [m["age_seconds"] for m in prov.values()
            if m["age_seconds"] is not None]
    # crosscheck's invariants are race invariants (lead changes, lapped
    # cars, gap monotonicity); other session kinds carry no verdict.
    cc = race.crosscheck() if hasattr(race, "crosscheck") else None

    warnings = []
    if lifecycle in ("in_progress", "provisional"):
        warnings.append(
            f"session is {lifecycle}: timing data is not final yet")
    if gap_counts["compound"]:
        warnings.append(
            f"{gap_counts['compound']} stint(s) have no compound recorded")
    if cov["laps"] is not None and cov["laps"] < 0.99:
        warnings.append(
            f"lap table holds {counts['present_laps']} of "
            f"{counts['expected_laps']} classified laps")
    if cov["sectors"] is not None and cov["sectors"] < 0.98:
        warnings.append(f"sector times {cov['sectors']:.1%} complete")
    for r in revs:
        warnings.append(
            f"source rewritten at {r['observed_at']} "
            f"({r.get('rows_added', 0)} row(s) changed) — "
            f"any earlier publication needs a correction notice")
    warnings += [f"crosscheck {c['status']}: {c['name']} — {c['detail']}"
                 for c in (cc or {}).get("checks", [])
                 if c["status"] != "ok"]

    return jsonsafe({
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "session": {"year": race.year, "round": race.round,
                    "session_key": race.session_key,
                    "name": race.name, "kind": race.KIND,
                    "meeting": race.meeting.get("meeting_name"),
                    "ended_at": race.info.get("date_end")},
        "state": state,
        "lifecycle": lifecycle,
        "coverage": cov,
        "missing": missing,
        "missing_counts": gap_counts,
        "missing_truncated": sum(gap_counts.values()) > len(missing),
        "source_age_seconds": max(ages) if ages else None,
        "provenance": prov,
        "revisions": revs,
        "crosscheck": cc,
        "warnings": warnings,
        "publishable": bool(
            (cc is None or cc["publishable"])
            and lifecycle not in ("in_progress", "provisional")
            and (cov["overall"] or 0) >= 0.95),
    })


# -- snapshot / diff --------------------------------------------------------

def snapshot(session) -> dict:
    """Normalised, hashed classification — the unit :func:`diff` compares.

    The rows are whatever that session kind publishes (gap and points for
    a race, segment times for qualifying), so a snapshot of one kind is
    only comparable with another of the same kind. Persist these to keep
    a correction ledger; the hash covers the rows only, so two snapshots
    of an unchanged classification compare equal whenever they were taken.
    """
    rows = session.results()
    return jsonsafe({
        "schema_version": SCHEMA_VERSION,
        "taken_at": _now(),
        "session": {"year": session.year, "round": session.round,
                    "session_key": session.session_key,
                    "name": session.name, "kind": session.KIND},
        "state": "corrected" if session.revisions() else session.lifecycle,
        "sha256": _digest(rows),
        "results": rows,
        "provenance": session.provenance(),
    })


def diff(before: dict, after: dict) -> dict:
    """Field-level changes between two :func:`snapshot` results.

    Rows are matched on driver code, so a disqualification reads as
    changed fields on the affected rows rather than a wholesale replace.
    Every field the two snapshots carry is compared, which keeps the
    function honest across session kinds.
    """
    a = {r["abbr"]: r for r in before.get("results", [])}
    b = {r["abbr"]: r for r in after.get("results", [])}
    fields = sorted({k for r in list(a.values()) + list(b.values())
                     for k in r} - {"abbr", "name"})
    changes = []
    for abbr in sorted(a.keys() & b.keys()):
        for field in fields:
            if a[abbr].get(field) != b[abbr].get(field):
                changes.append({"abbr": abbr, "field": field,
                                "before": a[abbr].get(field),
                                "after": b[abbr].get(field)})
    added, removed = sorted(b.keys() - a.keys()), sorted(a.keys() - b.keys())
    return jsonsafe({
        "schema_version": SCHEMA_VERSION,
        "changed": bool(changes or added or removed),
        "from": {"taken_at": before.get("taken_at"),
                 "sha256": before.get("sha256"),
                 "state": before.get("state")},
        "to": {"taken_at": after.get("taken_at"),
               "sha256": after.get("sha256"),
               "state": after.get("state")},
        "changes": changes,
        "added": added,
        "removed": removed,
    })


# --- deleted lap times -------------------------------------------------

_TIME_DELETED = re.compile(
    r"CAR (?P<car>\d{1,2}) .*?TIME (?P<time>\d+:\d{2}\.\d{3}) DELETED"
    r"(?:\s*-\s*(?P<why>.*))?", re.I)
_TIME_REINSTATED = re.compile(
    r"CAR (?P<car>\d{1,2}) .*?TIME (?P<time>\d+:\d{2}\.\d{3}).*REINSTATED",
    re.I)
_EMBEDDED_CLOCK = re.compile(r"\s*\d{2}:\d{2}:\d{2}\s*$")


def lap_deletions(messages: list) -> list:
    """Which lap times the stewards struck out, and which came back.

    Race control announces deletions in prose, and occasionally reverses
    one later in the session. Both halves matter: a deletion that was
    reinstated must not be treated as a deletion, and a consumer deciding
    which laps count needs to see the reversal, not have it silently
    swallowed. So this reads the whole message list twice — reversals
    first — and reports every deletion with a ``stands`` flag rather than
    dropping the reinstated ones.

    ``messages`` is the race-control list as the session object holds it
    (each row a dict with at least ``message``; ``date`` is carried
    through when present). The trailing session clock some stewards embed
    in the reason is stripped — it reads as a lap time and confuses more
    than it informs.
    """
    reinstated = set()
    for m in messages:
        hit = _TIME_REINSTATED.search(m.get("message") or "")
        if hit:
            reinstated.add((hit["car"], hit["time"]))
    out = []
    for m in messages:
        hit = _TIME_DELETED.search(m.get("message") or "")
        if not hit:
            continue
        key = (hit["car"], hit["time"])
        why = _EMBEDDED_CLOCK.sub("", hit["why"] or "").strip() or None
        out.append({"car_number": int(hit["car"]),
                    "lap_time": hit["time"],
                    "reason": why,
                    "stands": key not in reinstated,
                    "date": m.get("date")})
    return jsonsafe(out)
