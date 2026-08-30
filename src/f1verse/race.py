"""Race loader.

``f1verse.load(year, round)`` builds a :class:`Race` from public REST data
plus the official live-timing archive. Seasons 2023 onward.
"""
from datetime import datetime
from statistics import median

from . import feeds
from ._json import jsonsafe
from .gaps import format_seconds
from .sources import livetiming, openf1


def _iso(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Race:
    def __init__(self, year: int, rnd: int):
        self.year, self.round = year, rnd
        s = openf1.resolve_race(year, rnd)
        self.session_key = s["session_key"]
        self.meeting = s["meeting"]
        self.info = s
        self._api_path = None

        key = {"session_key": self.session_key}
        self.drivers = {d["driver_number"]: d for d in openf1.get("drivers", **key)}
        self.laps = sorted(openf1.get("laps", **key),
                           key=lambda l: (l["driver_number"], l["lap_number"]))
        self.result = openf1.get("session_result", **key)
        self.race_control = openf1.get("race_control", **key)
        self.stints_raw = openf1.get("stints", **key)
        self.pits = openf1.get("pit", **key)
        self._p1 = sorted(openf1.get("position", position=1, **key),
                          key=lambda p: p["date"])
        self.total_laps = max((l["lap_number"] for l in self.laps), default=0)

    # -- identity helpers ---------------------------------------------------
    def abbr(self, num) -> str:
        d = self.drivers.get(num, {})
        return d.get("name_acronym") or str(num)

    @property
    def api_path(self) -> str:
        """Live-timing archive path (resolved lazily, cached)."""
        if self._api_path is None:
            self._api_path = livetiming.api_path(
                self.year, self.meeting["meeting_name"])
        return self._api_path

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

    def interruptions(self) -> dict:
        """SC/VSC lap bands and red-flag laps from race control."""
        bands, red, start = [], [], None
        for m in sorted(self.race_control, key=lambda m: m["date"]):
            msg, lap = (m.get("message") or "").upper(), m.get("lap_number")
            if msg.startswith("RED FLAG") and lap:
                red.append(int(lap))
            if ("SAFETY CAR DEPLOYED" in msg or "VSC DEPLOYED" in msg
                    or "VIRTUAL SAFETY CAR DEPLOYED" in msg):
                start = int(lap or 1)
            if start is not None and ("ENDING" in msg or "IN THIS LAP" in msg
                                      or "CLEAR" in msg and "TRACK" in msg):
                bands.append([start, int(lap or start)])
                start = None
        if start is not None:
            bands.append([start, self.total_laps])
        return {"sc_vsc_bands": bands, "red_flag_laps": sorted(set(red))}

    def stints(self) -> dict:
        out = {}
        for s in sorted(self.stints_raw,
                        key=lambda s: (s["driver_number"], s["stint_number"])):
            out.setdefault(self.abbr(s["driver_number"]), []).append({
                "compound": s.get("compound"),
                "from": s.get("lap_start"), "to": s.get("lap_end"),
                "laps": (s.get("lap_end") or 0) - (s.get("lap_start") or 0) + 1})
        return out

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
        rows = sorted(self.result,
                      key=lambda r: (r.get("position") is None,
                                     r.get("position") or 0,
                                     -(r.get("number_of_laps") or 0)))
        out = []
        for r in rows:
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
            d = self.drivers.get(r["driver_number"], {})
            out.append({"position": r.get("position"),
                        "abbr": self.abbr(r["driver_number"]),
                        "name": d.get("full_name"),
                        "team": d.get("team_name"),
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
            "event": {"name": m["meeting_name"],
                      "location": self.info.get("location"),
                      "round": self.round, "year": self.year,
                      "date": (self.info.get("date_start") or "")[:10],
                      "total_laps": self.total_laps},
            "results": self.results(),
            "leader_runs": self.leader_runs(),
            "laps_led": self.laps_led(),
            "timeline": self.timeline(),
            "stints": self.stints(),
            "race_pace": self.race_pace(),
            "interruptions": self.interruptions(),
            "sources": ["openf1", "livetiming-index"],
        })


def load(year: int, rnd: int) -> Race:
    """``f1verse.load(2026, 12)`` → :class:`Race` (2023+ seasons)."""
    return Race(year, rnd)
