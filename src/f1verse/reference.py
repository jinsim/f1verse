# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Published circuit facts, and the machinery that keeps them honest.

Some things about a circuit are surveyed, published and stable: how long
the lap is, how many corners it has, which way it runs. Deriving those
from telemetry is the wrong tool — the measurement is noisier than the
published number and no more current. So they are recorded here, with the
source they came from and the date they were last checked.

The catch is that a stored fact fails silently. A table that says a lap
is 4.259 km stays confident after a circuit is shortened, and a wrong
entry is indistinguishable from a right one by reading it. That is
exactly the failure this library exists to catch elsewhere — provisional
classifications, expiring caches, journalled corrections — so the same
discipline applies here: every fact carries its provenance, and
:func:`audit` re-derives what it can from the cars and reports where the
two disagree.

That inverts the roles usefully. Telemetry is a poor surveyor and an
excellent auditor: measured lap distance lands within about half a
percent of a published length and the corner count is exact, which is far
too coarse to publish as a survey and far more than enough to notice that
a stored figure has gone stale.

Facts here are the kind that cannot be copyrighted — a length, a count, a
direction — and each names where it was read. Anything not verified is
absent rather than guessed: :func:`facts` returns ``None`` for a circuit
nobody has checked, and a caller can tell "we know it is 14" from "nobody
has looked".
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from ._json import jsonsafe

_HERE = os.path.dirname(os.path.abspath(__file__))
_TABLE = os.path.join(_HERE, "data", "circuits.json")

# How far a measurement may sit from a published figure before it is worth
# a human looking. Lap distance is derived from a driven line sampled a
# few times a second, so it is close but never exact; a corner count is a
# count and has no excuse.
TOLERANCE = {"length_m": 0.02, "corners": 0.0}

_cache = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(_TABLE, encoding="utf-8") as handle:
                _cache = json.load(handle)
        except (OSError, ValueError):
            _cache = {"circuits": {}}
    return _cache


def facts(circuit: str, wikipedia_url: str | None = None) -> dict | None:
    """Published facts for a circuit, or ``None`` if none can be had.

    Two layers, in order of trust. The curated table wins where it has an
    entry, because a human checked it. Where it is silent and an article
    is known, the figures come from Wikidata: it is CC0, it is upstream of
    the compiled Formula 1 databases rather than downstream of them, and
    it covers most of the championship's venues without anyone retyping a
    specification.

    Fields are merged rather than chosen wholesale, so a curated entry can
    correct a single wrong length without having to restate everything
    else, and ``provenance`` records which layer each value came from.
    ``None`` still means nobody has checked and nothing was published —
    which is a different statement from any particular value.
    """
    table = _load().get("circuits", {})
    curated = table.get(circuit)
    if curated is None:
        # the feeds disagree on names — Lusail and Losail, Singapore and
        # Marina Bay are each one circuit — so a miss falls back to the
        # names an entry says it also answers to
        curated = next((entry for entry in table.values()
                        if circuit in (entry.get("aliases") or [])), None)
    upstream = None
    if wikipedia_url:
        try:
            from .sources import wikidata
            fetched = wikidata.circuit_facts(wikipedia_url)
            upstream = fetched if fetched.get("available") else None
        except Exception:
            upstream = None
    if not curated and not upstream:
        return None

    merged, provenance = {"circuit": circuit}, {}
    for field in ("length_m", "corners", "direction", "opened",
                  "layout_since", "race_laps", "race_distance_km",
                  "coordinates", "notes"):
        if curated and curated.get(field) is not None:
            merged[field] = curated[field]
            provenance[field] = "curated"
        elif upstream and upstream.get(field) is not None:
            merged[field] = upstream[field]
            provenance[field] = "wikidata"
    merged["provenance"] = provenance
    merged["source"] = (curated or {}).get("source") or (upstream or {}).get("source")
    merged["checked"] = (curated or {}).get("checked")
    if upstream:
        merged["wikidata_id"] = upstream.get("wikidata_id")
    return jsonsafe(merged)


def known() -> list:
    """Every circuit with recorded facts."""
    return sorted(_load().get("circuits", {}))


def audit(circuit: str, measured: dict,
          wikipedia_url: str | None = None) -> dict:
    """Compare what is published against what the cars measured.

    ``measured`` is a survey result — anything carrying ``lap_distance_m``
    and a corner count. Each comparable field comes back as ``agrees``,
    ``differs`` or ``unchecked``, with both numbers and the gap between
    them, so a disagreement can be read without re-deriving it.

    A disagreement does not say which side is wrong. It says the two
    disagree, which is the fact a maintainer needs.
    """
    published = facts(circuit, wikipedia_url)
    if not published:
        return jsonsafe({
            "circuit": circuit, "verdict": "no reference",
            "reason": "no published facts recorded for this circuit",
        })

    checks = []
    pairs = (("length_m", measured.get("lap_distance_m")),
             ("corners", measured.get("corners")))
    for field, found in pairs:
        expected = published.get(field)
        if expected is None or found is None:
            checks.append({"field": field, "state": "unchecked",
                           "published": expected, "measured": found})
            continue
        gap = abs(found - expected) / expected if expected else None
        checks.append({
            "field": field,
            "state": "agrees" if gap is not None
                     and gap <= TOLERANCE.get(field, 0.02) else "differs",
            "published": expected,
            "measured": round(found, 1) if isinstance(found, float) else found,
            "off_by_percent": round(100 * gap, 2) if gap is not None else None,
        })
    differs = [c for c in checks if c["state"] == "differs"]
    return jsonsafe({
        "circuit": circuit,
        "verdict": "differs" if differs else
                   "agrees" if any(c["state"] == "agrees" for c in checks)
                   else "unchecked",
        "source": published.get("source"),
        "checked": published.get("checked"),
        # how long ago somebody last confirmed the stored figures, so a
        # consumer can weigh a passing audit against the age of what it
        # passed against
        "checked_age_days": _age_days(published.get("checked"), None),
        "provenance": published.get("provenance"),
        "checks": checks,
        "note": ("a difference names a disagreement, not a culprit: the "
                 "stored figure may be stale or the session may be short "
                 "of position data"),
    })


# --- keeping the table current -----------------------------------------
#
# A curated table is only as good as the last time somebody looked at it,
# and nothing about reading one tells you when that was. Circuits are
# resurfaced and reprofiled, calendars gain venues and lose them, and a
# season ends every year — so the table has to be able to say that it is
# behind, rather than waiting to be caught out by a wrong number.

# An entry older than a season is not necessarily wrong, but it has not
# been checked against a calendar that has since changed, and that is the
# point at which somebody should look.
REVIEW_AFTER_DAYS = 400

# Fields a fresh sweep of the official pages is authoritative for. Corner
# counts and human notes are not among them: nobody publishes the first
# and nobody but us writes the second, so a sweep must never clear them.
SWEPT = ("length_m", "race_laps", "race_distance_km", "first_grand_prix",
         "circuit_official_name", "circuit_type", "held_in")


def _age_days(checked: str, today: str | None) -> int | None:
    if not checked:
        return None
    try:
        then = datetime.strptime(checked[:10], "%Y-%m-%d")
        now = (datetime.strptime(today[:10], "%Y-%m-%d") if today
               else datetime.now(timezone.utc).replace(tzinfo=None))
    except (TypeError, ValueError):
        return None
    return (now - then).days


def stale(today: str | None = None, after_days: int = REVIEW_AFTER_DAYS) -> list:
    """Curated entries nobody has checked for longer than a season.

    Age is not error. It is the absence of evidence that the entry still
    matches the circuit, which is the thing a maintainer needs prompting
    about before a calendar turns over.
    """
    out = []
    for name, entry in sorted(_load().get("circuits", {}).items()):
        age = _age_days(entry.get("checked"), today)
        if age is None or age >= after_days:
            out.append({"circuit": name, "checked": entry.get("checked"),
                        "age_days": age,
                        "reason": "never dated" if age is None
                                  else "not checked since last season"})
    return jsonsafe(out)


def review(swept: dict, today: str | None = None) -> dict:
    """What a fresh sweep of the official pages would change.

    ``swept`` maps a circuit name to the specifications just read from the
    championship's own pages. The result separates four things a
    maintainer treats differently: circuits the sweep found that the table
    has never held, values that have moved since they were recorded,
    entries the sweep no longer covers, and entries that are simply old.

    Nothing is written. A changed length is as likely to be a reprofiled
    circuit as a broken parse, and the difference between those is a
    judgement, not a rule.
    """
    stored = _load().get("circuits", {})
    added, changed, unchanged = [], [], []
    for name in sorted(swept):
        fresh = swept[name]
        current = stored.get(name)
        if current is None:
            added.append({"circuit": name,
                          **{f: fresh.get(f) for f in SWEPT
                             if fresh.get(f) is not None}})
            continue
        moved = [{"field": f, "stored": current.get(f), "official": fresh.get(f)}
                 for f in SWEPT
                 if fresh.get(f) is not None and current.get(f) != fresh.get(f)]
        (changed if moved else unchanged).append(
            {"circuit": name, "changes": moved} if moved else name)
    return jsonsafe({
        "added": added,
        "changed": changed,
        "unchanged": unchanged,
        "not_in_sweep": sorted(set(stored) - set(swept)),
        "stale": stale(today),
        "note": ("a moved value is a reprofiled circuit or a broken parse, "
                 "and telling those apart is a judgement — this reports, "
                 "it does not write"),
    })
