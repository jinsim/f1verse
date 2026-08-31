# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Races before the live-timing era — 1996 to 2022.

:class:`~f1verse.race.Race` needs the per-session feeds that only exist
from 2023. That boundary is a property of one source, not of the sport,
and treating it as the edge of the world throws away twenty-seven seasons
that are fully documented elsewhere: lap-by-lap timings reach back to
1996 and pit stops to 2011.

So this module answers the same questions for the older seasons, and is
explicit about the ones it cannot answer. Every return value carries a
``coverage`` block naming what the era actually holds — a caller can
branch on it, and nothing here ever invents a field the data does not
support. Where a season *does* have the modern feeds, use ``Race``; it
knows strictly more.
"""
from __future__ import annotations

from ._json import jsonsafe
from .sources import jolpica

LAPS_FROM = 1996        # lap-by-lap timings begin
PITS_FROM = 2011        # pit stops begin
NATIVE_FROM = 2023      # the live-timing feeds Race is built on


def coverage(year: int) -> dict:
    """What a season of this era can and cannot answer."""
    has_laps, has_pits = year >= LAPS_FROM, year >= PITS_FROM
    return {
        "year": year,
        "results": True, "qualifying": True, "standings": True,
        "lap_times": has_laps, "running_order": has_laps,
        "pit_stops": has_pits,
        "stints": year >= NATIVE_FROM, "telemetry": year >= NATIVE_FROM,
        "weather": year >= NATIVE_FROM, "race_control": year >= NATIVE_FROM,
        "note": ("full live-timing coverage" if year >= NATIVE_FROM else
                 "lap times and pit stops" if has_pits else
                 "lap times only" if has_laps else
                 "results and standings only"),
    }


def _seconds(text: str):
    """``"1:23.456"`` → 83.456."""
    if not text:
        return None
    try:
        if ":" in text:
            m, s = text.split(":", 1)
            return round(int(m) * 60 + float(s), 3)
        return float(text)
    except ValueError:
        return None


class ArchiveRace:
    """A pre-2023 race, assembled from the historic record.

    Built by :func:`load_archive`. Carries the same vocabulary as
    :class:`~f1verse.race.Race` where the data allows — ``results``,
    ``running_order``, ``laps_led`` — and simply omits what the era never
    recorded rather than approximating it.
    """

    def __init__(self, year: int, rnd: int):
        self.year, self.round = year, rnd
        self.coverage = coverage(year)
        d = jolpica.get(f"{year}/{rnd}/results")
        races = d["RaceTable"]["Races"]
        if not races:
            raise LookupError(f"no race found for {year} round {rnd}")
        self.info = races[0]
        self.name = self.info.get("raceName")
        self.circuit = self.info.get("Circuit", {}).get("circuitName")
        self.date = self.info.get("date")
        self._results = self.info.get("Results", [])
        self._laps = (jolpica.lap_timings(year, rnd)
                      if self.coverage["lap_times"] else [])
        self._pits = (jolpica.pit_stops(year, rnd)
                      if self.coverage["pit_stops"] else [])
        self._code = {r["Driver"]["driverId"]:
                      (r["Driver"].get("code")
                       or r["Driver"]["familyName"][:3].upper())
                      for r in self._results}

    def __repr__(self) -> str:
        return (f"<ArchiveRace {self.year} r{self.round} {self.name!r} "
                f"{self.coverage['note']}>")

    def abbr(self, driver_id: str) -> str:
        return self._code.get(driver_id, driver_id[:3].upper())

    @property
    def total_laps(self) -> int:
        return max((l["lap"] for l in self._laps), default=0)

    def results(self) -> list:
        out = []
        for r in self._results:
            out.append({
                "position": int(r["position"]) if r["position"].isdigit()
                            else None,
                "classified": r["positionText"],
                "abbr": self.abbr(r["Driver"]["driverId"]),
                "driver": f"{r['Driver']['givenName']} "
                          f"{r['Driver']['familyName']}",
                "team": r["Constructor"]["name"],
                "grid": int(r["grid"]), "laps": int(r["laps"]),
                "status": r["status"], "points": float(r["points"]),
                "time": (r.get("Time") or {}).get("time"),
                "fastest_lap": ((r.get("FastestLap") or {}).get("Time")
                                or {}).get("time"),
            })
        return jsonsafe(out)

    def running_order(self) -> dict:
        """``{lap: [abbr, ...]}`` — the order on track at the end of each
        lap. The whole point of reaching back past 2023."""
        return jsonsafe(self._order())

    def _order(self) -> dict:
        """Integer-keyed running order for internal use — ``jsonsafe``
        stringifies keys, and string keys sort ``"10"`` before ``"2"``."""
        return {l["lap"]: [self.abbr(t["driverId"]) for t in
                           sorted(l["timings"],
                                  key=lambda t: int(t["position"]))]
                for l in self._laps}

    def lap_times(self, driver: str) -> list:
        """``[{"lap": n, "seconds": s, "position": p}, ...]`` for one
        driver, given their three-letter code."""
        out = []
        for l in self._laps:
            for t in l["timings"]:
                if self.abbr(t["driverId"]) == driver.upper():
                    out.append({"lap": l["lap"],
                                "seconds": _seconds(t.get("time")),
                                "position": int(t["position"])})
        return jsonsafe(out)

    def leader_runs(self) -> list:
        """Unbroken spells in the lead, in order."""
        runs = []
        for l in self._laps:
            lead = next((self.abbr(t["driverId"]) for t in l["timings"]
                         if t["position"] == "1"), None)
            if lead is None:
                continue
            if runs and runs[-1]["abbr"] == lead:
                runs[-1]["to"] = l["lap"]
            else:
                runs.append({"abbr": lead, "from": l["lap"], "to": l["lap"]})
        return jsonsafe(runs)

    def laps_led(self) -> dict:
        led: dict = {}
        for r in self.leader_runs():
            led[r["abbr"]] = led.get(r["abbr"], 0) + r["to"] - r["from"] + 1
        return jsonsafe(led)

    def pit_stops(self) -> list:
        return jsonsafe([{**p, "abbr": self.abbr(p["driver_id"])}
                         for p in self._pits])

    def story(self) -> dict:
        """Everything this era can say about the race, in one call."""
        runs = self.leader_runs()
        return jsonsafe({
            "event": {"name": self.name, "circuit": self.circuit,
                      "date": self.date, "year": self.year,
                      "round": self.round, "total_laps": self.total_laps},
            "coverage": self.coverage,
            "results": self.results(),
            "leader_runs": runs,
            "laps_led": self.laps_led(),
            "lead_changes": max(len(runs) - 1, 0),
            "pit_stops": self.pit_stops(),
        })


def load_archive(year: int, rnd: int) -> ArchiveRace:
    """``load_archive(2008, 18)`` → :class:`ArchiveRace`.

    Works for any season Jolpica documents. For 2023 onward prefer
    :func:`f1verse.load`, which has the live-timing feeds as well.
    """
    return ArchiveRace(year, rnd)
