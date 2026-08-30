"""Race loader — the story a race session tells.

``f1verse.load(year, round)`` builds a :class:`Race` from public REST data
plus the official live-timing archive. Seasons 2023 onward.

:class:`Race` extends :class:`f1verse.session.Session` with what only a
race has: a lead that changes hands, a representative pace once the
neutralised laps are excluded, and a timeline of the things that decided
it. ``f1verse.load_session`` loads the other sessions of the weekend.
"""
from datetime import datetime
from statistics import median

from . import feeds
from ._json import jsonsafe
from .gaps import format_seconds
from .session import SCHEMA_VERSION, Session, session_class
from .sources import openf1


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Race(Session):
    """A race or sprint: classification, lead, pace, timeline, story."""

    KIND = "Race"

    # -- story --------------------------------------------------------------
    def leader_runs(self) -> list:
        """Lead spells on the lap axis, from the P1 position stream."""
        events, prev = [], None
        for p in self._p1:
            if p["driver_number"] != prev:
                events.append((_iso(p["date"]), p["driver_number"]))
                prev = p["driver_number"]
        by_drv = {}
        for l in self.laps:
            if l.get("date_start"):
                by_drv.setdefault(l["driver_number"], []).append(
                    (_iso(l["date_start"]), l["lap_number"]))
        runs = []
        for t, num in events:
            lap = 1
            for ts, ln in by_drv.get(num, []):
                if ts <= t:
                    lap = ln
                else:
                    break
            if runs and runs[-1]["abbr"] == self.abbr(num):
                continue
            if runs:
                runs[-1]["to"] = max(lap - 1, runs[-1]["from"])
            runs.append({"abbr": self.abbr(num), "from": lap, "to": lap})
        if runs:
            runs[-1]["to"] = self.total_laps
        return runs

    def laps_led(self) -> dict:
        led = {}
        for r in self.leader_runs():
            led[r["abbr"]] = led.get(r["abbr"], 0) + r["to"] - r["from"] + 1
        return dict(sorted(led.items(), key=lambda kv: -kv[1]))

    def race_pace(self, threshold: float = 1.07) -> dict:
        """Median representative pace. Domain rules by default:
        pit-out laps, pit-in laps, SC/VSC laps and quicklap threshold."""
        bad = {l for a, b in self.interruptions()["sc_vsc_bands"]
               for l in range(a, b + 1)}
        pit_in = {(p["driver_number"], p["lap_number"]) for p in self.pits}
        per = {}
        for l in self.laps:
            d = l.get("lap_duration")
            if (not d or l.get("is_pit_out_lap")
                    or l["lap_number"] in bad
                    or (l["driver_number"], l["lap_number"]) in pit_in):
                continue
            per.setdefault(l["driver_number"], []).append(d)
        out = {}
        for num, ds in per.items():
            m = median(ds)
            quick = [x for x in ds if x <= m * threshold]
            if len(quick) >= 3:
                out[self.abbr(num)] = round(median(quick), 3)
        return dict(sorted(out.items(), key=lambda kv: kv[1]))

    def results(self) -> list:
        """Classified results; OpenF1 already applies '+1 LAP' convention.
        FIA gives DNFs no position — ordered by laps completed after that."""
        out = []
        for r in self._ordered():
            g = r.get("gap_to_leader")
            if r.get("dsq"):
                gap = "DSQ"
            elif r.get("dnf") or r.get("dns"):
                gap = "DNS" if r.get("dns") else "DNF"
            elif r.get("position") == 1:
                gap = "WINNER"
            elif isinstance(g, str):
                gap = g if g.startswith("+") else f"+{g}"
            elif g is None:
                gap = ""
            else:
                gap = format_seconds(float(g))
            out.append({"position": r.get("position"),
                        **self._entry(r["driver_number"]),
                        "gap": gap, "points": r.get("points") or 0.0,
                        "laps": r.get("number_of_laps")})
        return out

    def timeline(self) -> list:
        ev = []
        for r in self.result:
            if r.get("dnf"):
                ab = self.abbr(r["driver_number"])
                last = max((l["lap_number"] for l in self.laps
                            if l["driver_number"] == r["driver_number"]),
                           default=0)
                ev.append({"lap": last, "kind": "out", "abbr": ab,
                           "title": f"{ab} out"})
        inter = self.interruptions()
        ev += [{"lap": l, "kind": "red", "title": "Red flag"}
               for l in inter["red_flag_laps"]]
        ev += [{"lap": a, "kind": "sc", "title": f"SC/VSC (laps {a}-{b})"}
               for a, b in inter["sc_vsc_bands"]]
        runs = self.leader_runs()
        ev += [{"lap": cur["from"], "kind": "lead", "abbr": cur["abbr"],
                "over": prev["abbr"],
                "title": f"{cur['abbr']} leads (from {prev['abbr']})"}
               for prev, cur in zip(runs, runs[1:])]
        return sorted(ev, key=lambda e: (e["lap"], e["kind"]))

    def crosscheck(self) -> dict:
        """Independent-source validation — gate publication on this."""
        from .crosscheck import crosscheck
        return crosscheck(self)

    # -- dropped-feed harvest ------------------------------------------------
    def championship_prediction(self) -> dict:
        return feeds.championship_prediction(self)

    def team_radio(self) -> list:
        return feeds.team_radio(self)

    def timing_stats(self) -> dict:
        return feeds.timing_stats(self)

    def story(self) -> dict:
        """One call, whole story — JSON-safe."""
        m = self.meeting
        return jsonsafe({
            "schema_version": SCHEMA_VERSION,
            "event": {"name": m["meeting_name"],
                      "location": self.info.get("location"),
                      "round": self.round, "year": self.year,
                      "session": self.name,
                      "date": (self.info.get("date_start") or "")[:10],
                      "total_laps": self.total_laps},
            "results": self.results(),
            "leader_runs": self.leader_runs(),
            "laps_led": self.laps_led(),
            "timeline": self.timeline(),
            "stints": self.stints(),
            "race_pace": self.race_pace(),
            "interruptions": self.interruptions(),
            "state": self.lifecycle,
            "sources": ["openf1", "livetiming-index"],
        })


def load(year: int, rnd: int) -> Race:
    """``f1verse.load(2026, 12)`` → :class:`Race` (2023+ seasons)."""
    return Race(year, rnd)


def load_session(year: int, rnd: int, session: str = "Race"):
    """Any session of a weekend, as the right kind of object.

    >>> f1verse.load_session(2026, 12, "Qualifying").segments()["q3"]

    *session* is matched as OpenF1 spells it — ``Race``, ``Qualifying``,
    ``Sprint``, ``Sprint Qualifying``, ``Practice 1``… A sprint is a race
    and loads as :class:`Race`; sprint qualifying loads as
    :class:`~f1verse.session.Qualifying`. Unknown names raise
    ``LookupError`` listing the sessions that weekend actually had.
    """
    s = openf1.resolve_session(year, rnd, session)
    cls = session_class(s["session_name"], s.get("session_type"))
    return cls(year, rnd, s["session_name"])


def sessions(year: int, rnd: int) -> list:
    """What sessions that round has, in order — the input to *load_session*."""
    meeting = openf1.resolve_session(year, rnd, "Race")["meeting"]
    return jsonsafe([
        {"session": s["session_name"], "type": s.get("session_type"),
         "session_key": s["session_key"], "start": s["date_start"],
         "end": s["date_end"]}
        for s in sorted(openf1.get("sessions", meeting_key=meeting["meeting_key"]),
                        key=lambda s: s["date_start"])])
