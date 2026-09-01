# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Bring the curated circuit table up to date with the official pages.

Run it when a season is announced, when a circuit is reprofiled, or when
``f1verse.reference.stale()`` starts naming entries. With no year it
sweeps the season that is running now, which is what makes this survive
the turn of a calendar without anyone editing the script.

    python scripts/refresh_circuits.py            # this season, diff only
    python scripts/refresh_circuits.py 2027       # a specific season
    python scripts/refresh_circuits.py 2027 --write

Without ``--write`` it reports and changes nothing. That default is the
point: a length that has moved is either a rebuilt circuit or a parse that
broke against a redesigned page, and only a person can tell those apart.

Matching an official event page to a circuit is the awkward part: the
season index is ordered from today rather than from round one, and a
country can host more than one race (three in the United States, two in
Spain), so neither position nor country identifies an event on its own.
Slug words are therefore scored against the circuit's own name, its
location and its country, and anything that does not match confidently is
printed as unresolved rather than guessed at.
"""
import collections
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, "src")

from f1verse import reference  # noqa: E402
from f1verse.sources import formula1, openf1  # noqa: E402


def _by_key(year):
    """The season's circuits, indexed by the event key both feeds share."""
    keyed = {}
    for meeting in openf1.get("meetings", year=year):
        if meeting.get("is_cancelled"):
            continue
        keyed[str(meeting.get("meeting_key"))] = meeting
    return keyed


def _apply(proposals, year):
    """Merge a sweep into the table, keeping everything a person wrote."""
    path = os.path.join("src", "f1verse", "data", "circuits.json")
    with open(path, encoding="utf-8") as handle:
        table = json.load(handle, object_pairs_hook=collections.OrderedDict)
    circuits = table["circuits"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for name, spec in proposals.items():
        entry = circuits.get(name) or collections.OrderedDict()
        for field in reference.SWEPT:
            value = spec.get(field)
            if value is not None:
                entry[field] = value
        entry["f1_slug"] = spec["f1_slug"]
        entry["source"] = "%s (season %d)" % (spec["source"], year)
        entry["checked"] = today
        circuits[name] = entry
    table["circuits"] = collections.OrderedDict(sorted(circuits.items()))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(table, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return path


def main(year=None, write=False):
    year = year or datetime.now(timezone.utc).year
    specs = formula1.season_specs(year)
    meetings = _by_key(year)
    proposals, unresolved = {}, []
    for slug, spec in specs.items():
        if not spec.get("available"):
            unresolved.append((slug, spec.get("reason", "unparsed")))
            continue
        meeting = meetings.get(str(spec.get("meeting_key")))
        # the official page and the timing feed share an event key, so the
        # two join exactly; a name match would have to guess between three
        # races in one country and two spellings of one circuit
        name = (meeting or {}).get("circuit_short_name") or \
            spec.get("circuit_short_name")
        if not name:
            unresolved.append((slug, "no event key match and no circuit name"))
            continue
        proposals[name] = {
            "length_m": spec["length_m"],
            "race_laps": spec["race_laps"],
            "race_distance_km": spec["race_distance_km"],
            "first_grand_prix": spec["first_grand_prix"],
            "circuit_official_name": spec.get("circuit_official_name"),
            "circuit_type": spec.get("circuit_type"),
            "held_in": spec.get("circuit_location"),
            "f1_slug": slug,
            "source": spec["source"],
            "checked": None,
        }
    swept = {name: {field: spec.get(field) for field in reference.SWEPT}
             for name, spec in proposals.items()}
    verdict = reference.review(swept)

    print("season %d — %d events swept, %d unresolved" % (
        year, len(proposals), len(unresolved)))
    for name in verdict["added"]:
        print("  NEW      %s" % name["circuit"])
    for row in verdict["changed"]:
        for change in row["changes"]:
            print("  CHANGED  %-20s %-22s %s -> %s" % (
                row["circuit"], change["field"], change["stored"],
                change["official"]))
    print("  unchanged %d | not in this sweep %d | stale %d" % (
        len(verdict["unchanged"]), len(verdict["not_in_sweep"]),
        len(verdict["stale"])))
    for row in verdict["stale"]:
        print("  STALE    %-20s last checked %s" % (row["circuit"],
                                                    row["checked"]))
    for slug, why in unresolved:
        print("  SKIPPED  %-20s %s" % (slug, why))

    if not write:
        print("\nnothing written. Re-run with --write once the changes above "
              "read as real.")
        return
    print("\nwrote %s" % _apply(proposals, year))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(int(args[0]) if args else None, write="--write" in sys.argv)
