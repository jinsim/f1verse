# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Session loader — one object for every kind of session on a weekend.

A Grand Prix weekend is not one session. Qualifying decides the grid,
sprints score points, practice is where long-run pace shows up, and all
four share the same shape: drivers, laps, stints, pit stops, race control
and a classification. :class:`Session` holds that shape; the race-specific
story lives in :class:`f1verse.race.Race`, which extends it.

What differs between session types is the **classification**, and it
differs enough that one formatter would lie about three of them:

- race and sprint publish a gap to the winner, plus points;
- qualifying publishes three segment times, where the gap in each segment
  is to that segment's fastest lap — the pole-sitter is often *not*
  fastest in Q1 — plus the segment a driver was knocked out in;
- practice publishes one best lap and a delta to the fastest.

So :meth:`Session.results` is overridden per kind rather than shared.
"""
from __future__ import annotations

from . import http, schedule
from .gaps import format_seconds
from .sources import livetiming, openf1

SCHEMA_VERSION = 1   # contract version of the JSON these methods return

_SEGMENTS = ("q1", "q2", "q3")


class Session:
    """A loaded session. Use :func:`f1verse.load_session` to build one."""

    KIND = "Session"

    def __init__(self, year: int, rnd: int, session_name: str = "Race"):
        self.year, self.round = year, rnd
        s = openf1.resolve_session(year, rnd, session_name)
        self.session_key = s["session_key"]
        self.meeting = s["meeting"]
        self.info = s
        self.name = s["session_name"]
        self._api_path = None
        self._load()

    def __repr__(self) -> str:
        return (f"<{type(self).__name__} {self.year} r{self.round} "
                f"{self.name!r} {self.lifecycle}>")

    # -- loading ------------------------------------------------------------
    @property
    def lifecycle(self) -> str:
        """``in_progress`` / ``provisional`` / ``settled`` / ``final``."""
        return schedule.lifecycle(self.info["date_end"])

    def _load(self, *, force: bool = False) -> None:
        """Fetch the session's rows, honouring how revisable they still are.

        Rows the stewards can rewrite are cached forever only once the
        session is ``final``; before that they carry a short TTL, so a
        disqualification or an amended penalty is actually seen rather
        than served from a copy taken at the flag.
        """
        key = {"session_key": self.session_key}
        live = self.lifecycle in ("in_progress", "provisional")
        ttl = 0 if force else (http.TTL_FOREVER if self.lifecycle == "final"
                               else http.TTL_PROVISIONAL)
        growing_ttl = 0 if force else (http.TTL_LIVE if live else http.TTL_FOREVER)
        self._availability = {}

        def read(endpoint, *, optional=False, **params):
            cache_ttl = ttl if endpoint in openf1.REVISABLE else growing_ttl
            if live and not force:
                cache_ttl = http.TTL_LIVE
            try:
                rows = openf1.get(endpoint, ttl=cache_ttl, **key, **params)
            except (http.SourceUnavailable, OSError, http.BudgetExhausted) as exc:
                if not optional:
                    raise
                self._availability[endpoint] = {
                    "status": getattr(exc, "status", http._failure(exc)),
                    "rows": None, "reason": str(exc)}
                return []
            meta = openf1.meta(endpoint, **key, **params)
            self._availability[endpoint] = {
                "status": "stale" if meta.get("stale_on_error") else "available",
                "rows": len(rows), "reason": None}
            return rows

        self.drivers = {d["driver_number"]: d for d in read("drivers")}
        self.laps = sorted(read("laps"),
                           key=lambda l: (l["driver_number"], l["lap_number"]))
        self.result = read("session_result")
        self.race_control = read("race_control", optional=True)
        self.stints_raw = read("stints", optional=True)
        self.pits = read("pit", optional=True)
        if getattr(self, "name", "Race") in ("Race", "Sprint"):
            self._p1 = sorted(read("position", optional=True, position=1),
                              key=lambda p: p["date"])
        else:
            self._p1 = []
            self._availability["position"] = {"status": "not_applicable", "rows": None,
                                              "reason": "P1 stream is not a classification input"}
        self.total_laps = max((l["lap_number"] for l in self.laps), default=0)

    def refresh(self):
        """Force a re-fetch of the revisable rows and rebuild.

        The escape hatch for corrections landing after a session is
        ``final`` — an appeal, a late amendment. Any change is journalled,
        so :meth:`quality_report` then reports the session as ``corrected``.
        """
        self._load(force=True)
        return self

    # -- identity -----------------------------------------------------------
    def abbr(self, num) -> str:
        d = self.drivers.get(num, {})
        return d.get("name_acronym") or str(num)

    def _entry(self, num) -> dict:
        d = self.drivers.get(num, {})
        return {"abbr": self.abbr(num), "name": d.get("full_name"),
                "team": d.get("team_name")}

    @property
    def api_path(self) -> str:
        """Live-timing archive path (resolved lazily, cached)."""
        if self._api_path is None:
            self._api_path = livetiming.api_path(
                self.year, self.meeting["meeting_name"], self.name)
        return self._api_path

    def availability(self) -> dict:
        """Endpoint coverage; unavailable and empty are different states."""
        from ._json import jsonsafe
        return jsonsafe(getattr(self, "_availability", {}))

    # -- provenance ---------------------------------------------------------
    def provenance(self) -> dict:
        """Per-endpoint cache provenance backing this object."""
        key = {"session_key": self.session_key}
        rows = {"drivers": self.drivers, "laps": self.laps,
                "session_result": self.result,
                "race_control": self.race_control,
                "stints": self.stints_raw, "pit": self.pits,
                "position": self._p1}
        out = {}
        for ep, data in rows.items():
            m = openf1.meta(ep, **key, **({"position": 1} if ep == "position" else {}))
            out[ep] = {"fetched_at": m["fetched_at"],
                       "age_seconds": m["age_seconds"],
                       "sha256": (m["sha256"] or "")[:16] or None,
                       "rows": len(data),
                       "revisable": ep in openf1.REVISABLE,
                       "access": m.get("access", {}),
                       "stale_on_error": m.get("stale_on_error", False)}
        return out

    def revisions(self) -> list:
        """Changes observed in this session's rows, oldest first."""
        return http.revisions(f"session_key={self.session_key}")

    # -- shared views -------------------------------------------------------
    def _ordered(self) -> list:
        """Classification order; rows without a position sort last."""
        return sorted(self.result,
                      key=lambda r: (r.get("position") is None,
                                     r.get("position") or 0,
                                     -(r.get("number_of_laps") or 0)))

    def results(self) -> list:
        """Best lap and delta to the fastest — the practice convention."""
        out = []
        for r in self._ordered():
            d = r.get("duration")
            g = r.get("gap_to_leader")
            out.append({"position": r.get("position"), **self._entry(r["driver_number"]),
                        "best_lap": d if isinstance(d, (int, float)) else None,
                        "gap": ("" if r.get("position") == 1 or g in (None, 0)
                                else format_seconds(float(g))
                                if isinstance(g, (int, float)) else ""),
                        "laps": r.get("number_of_laps")})
        return out

    def stints(self) -> dict:
        out = {}
        for s in sorted(self.stints_raw,
                        key=lambda s: (s["driver_number"], s["stint_number"])):
            out.setdefault(self.abbr(s["driver_number"]), []).append({
                "compound": s.get("compound"),
                "from": s.get("lap_start"), "to": s.get("lap_end"),
                "laps": (s.get("lap_end") or 0) - (s.get("lap_start") or 0) + 1})
        return out

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

    # -- quality ------------------------------------------------------------
    def quality_report(self) -> dict:
        """Why this data can (or cannot) be trusted — see :mod:`quality`."""
        from .quality import quality_report
        return quality_report(self)

    def snapshot(self) -> dict:
        """Hashed, comparable record of the classification as it stands now."""
        from .quality import snapshot
        return snapshot(self)


class Qualifying(Session):
    """Qualifying or sprint qualifying — three segments, three cut lines."""

    KIND = "Qualifying"

    def results(self) -> list:
        """Per-segment times, and the segment each driver went out in.

        ``gap`` is against the fastest lap **of that segment**, which is
        how the timing screen shows it: a pole-sitter who saved a set in
        Q1 shows a positive Q1 gap and a zero Q3 gap.
        """
        out = []
        for r in self._ordered():
            times = r.get("duration") or []
            gaps = r.get("gap_to_leader") or []
            seg = {}
            for i, name in enumerate(_SEGMENTS):
                t = times[i] if i < len(times) else None
                g = gaps[i] if i < len(gaps) else None
                seg[name] = t
                seg[name + "_gap"] = (round(float(g), 3)
                                      if isinstance(g, (int, float)) else None)
            run = [n for n in _SEGMENTS if seg[n] is not None]
            out.append({"position": r.get("position"),
                        **self._entry(r["driver_number"]), **seg,
                        "best": seg[run[-1]] if run else None,
                        "eliminated_in": (None if len(run) == len(_SEGMENTS)
                                          else (run[-1] if run else "Q1")),
                        "laps": r.get("number_of_laps"),
                        "status": ("DSQ" if r.get("dsq") else
                                   "DNS" if r.get("dns") else
                                   "DNF" if r.get("dnf") else "")})
        return out

    def segments(self) -> dict:
        """Cut lines: who advanced out of each segment, and the margin."""
        rows = self.results()
        out = {}
        for i, name in enumerate(_SEGMENTS):
            ran = [r for r in rows if r[name] is not None]
            if not ran:
                continue
            ran.sort(key=lambda r, n=name: r[n])
            last = i + 1 == len(_SEGMENTS)
            advanced = ([] if last else
                        [r for r in rows if r[_SEGMENTS[i + 1]] is not None])
            out[name] = {
                "ran": [r["abbr"] for r in ran],
                "fastest": ran[0]["abbr"],
                "fastest_time": ran[0][name],
                # the final segment has no cut — None, not an empty list
                "advanced": None if last else [r["abbr"] for r in advanced],
                "eliminated": [r["abbr"] for r in rows
                               if r["eliminated_in"] == name],
                # margin between the last car through and the first one out
                "cut_margin": (round(ran[len(advanced)][name]
                                     - ran[len(advanced) - 1][name], 3)
                               if advanced and len(ran) > len(advanced) else None),
            }
        return out


class Practice(Session):
    """A practice session. Classification is a best-lap table."""

    KIND = "Practice"


_KINDS = {"Race": None, "Qualifying": Qualifying, "Practice": Practice}


def session_class(session_name: str, session_type: str | None = None):
    """Pick the class for a session, by OpenF1 ``session_type``."""
    from .race import Race
    kind = session_type or ("Qualifying" if "Qualif" in session_name
                            else "Practice" if "Practice" in session_name
                            else "Race")
    return _KINDS.get(kind) or Race
