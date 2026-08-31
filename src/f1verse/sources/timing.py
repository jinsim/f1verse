# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Lap tables rebuilt from the raw timing patch stream.

``TimingData.jsonStream`` is not a table of laps — it is a stream of
partial updates in arrival order, and arrival order lies. A sector time
routinely lands *after* the car has already started its next lap; a lap
time for the previous lap arrives while the counter already says the new
one; a qualifying stream carries phantom "lap times" that are really the
gap between two runs. Rebuilding honest laps from that is a small state
machine with a handful of empirical rules, all of them encoded here with
their reasons:

- **The grace window.** A timing value arriving within a few seconds of a
  lap change describes the lap that just ended, not the one that just
  began — the message was simply slow. The one exception is the speed
  trap near the start line, which genuinely belongs to the new lap.
- **The credibility ceiling.** A "lap time" longer than any real racing
  lap is an artefact of session structure (a garage visit between
  qualifying runs, a red-flag pause) and is discarded, not stored.
- **Blank is a statement.** A field the stream never mentioned is
  unknown; a field the stream explicitly sent as ``""`` is the feed
  saying *there is no value*. Only the second case licenses computing a
  lap time from its sectors — summing sectors over an unknown is how
  parser bugs get papered over.
- **The earliest witness wins.** A lap's end can be timed three ways
  (when the last sector value arrived, or counted forward from an earlier
  sector's arrival). Messages can be late but never early, so the
  earliest candidate carries the least delay and is the one to trust.

Everything here is arithmetic on the record stream; nothing reaches for
the network.
"""
from __future__ import annotations

from .._clock import lap_seconds

# A value landing this soon after a lap change belongs to the lap before.
GRACE_S = 5.0
# No racing lap is this long; anything above it is session structure.
LONGEST_CREDIBLE_LAP_S = 150.0


def _new_lap(number: int, started: float | None) -> dict:
    return {"lap": number, "started": started, "time_s": None,
            "declared_blank": False, "filled_from_sectors": False,
            "sectors_s": [None, None, None], "sector_seen": [None, None, None],
            "speeds_kmh": {}, "pit_in": None, "pit_out": None}


def _value(field) -> str | None:
    """Timing fields arrive as ``{"Value": "..."}`` or occasionally bare."""
    if isinstance(field, dict):
        return field.get("Value")
    return field if isinstance(field, str) else None


def _indexed(field) -> list:
    """Sectors and speeds arrive as dicts keyed by stringified index —
    and, at the very start of a session, sometimes as real lists."""
    if isinstance(field, dict):
        out = []
        for k, v in field.items():
            try:
                out.append((int(k), v))
            except (TypeError, ValueError):
                continue
        return sorted(out)
    if isinstance(field, list):
        return list(enumerate(field))
    return []


class _Driver:
    """Accumulates one driver's laps as patches arrive."""

    def __init__(self):
        self.laps = [_new_lap(1, None)]
        self.feed_count = 0     # the stream's own lap counter, monotonic

    # -- which lap does a value describe? -------------------------------
    def _target(self, t: float, late_ok: bool = True) -> dict:
        cur = self.laps[-1]
        if (late_ok and len(self.laps) > 1 and cur["started"] is not None
                and t - cur["started"] < GRACE_S):
            return self.laps[-2]
        return cur

    def apply(self, t: float, line: dict) -> None:
        n = line.get("NumberOfLaps")
        if isinstance(n, int) and n > self.feed_count:
            self.feed_count = n
            if self.laps[-1]["started"] is not None:
                self.laps.append(_new_lap(self.laps[-1]["lap"] + 1, t))
            else:
                self.laps[-1]["started"] = t

        if "LastLapTime" in line:
            v = _value(line["LastLapTime"])
            lap = self._target(t)
            if v == "":
                lap["declared_blank"] = True
            elif v is not None:
                secs = lap_seconds(v)
                if secs is not None and secs <= LONGEST_CREDIBLE_LAP_S:
                    lap["time_s"] = secs

        for i, field in _indexed(line.get("Sectors")):
            v = lap_seconds(_value(field) or "")
            if v is None or not 0 <= i < 3:
                continue
            lap = self._target(t)
            lap["sectors_s"][i] = v
            lap["sector_seen"][i] = t

        for trap, field in (line.get("Speeds") or {}).items():
            v = lap_seconds(_value(field) or "")
            if v is None:
                continue
            # the start-line trap fires early in the *new* lap — the one
            # reading the grace window must not steal
            lap = self._target(t, late_ok=(trap != "ST"))
            lap["speeds_kmh"][trap] = v

        if line.get("InPit") is True:
            self._target(t)["pit_in"] = t
        elif line.get("PitOut") is True or line.get("InPit") is False:
            self.laps[-1]["pit_out"] = t

    # -- finishing touches ----------------------------------------------
    def table(self) -> list:
        laps = self.laps

        def ghost(lap):
            return (lap["time_s"] is None and not any(lap["sectors_s"])
                    and not lap["speeds_kmh"]
                    and lap["pit_in"] is None and lap["pit_out"] is None)

        while laps and ghost(laps[-1]):
            laps.pop()
        while laps and ghost(laps[0]):
            laps.pop(0)
            for lap in laps:
                lap["lap"] -= 1

        for lap in laps:
            if lap["declared_blank"] and lap["time_s"] is None:
                s = lap["sectors_s"]
                if all(v is not None for v in s):
                    lap["time_s"] = round(sum(s), 3)
                    lap["filled_from_sectors"] = True
            lap["ended"] = _earliest_end(lap)
            del lap["sector_seen"], lap["declared_blank"]
        return laps


def _earliest_end(lap: dict) -> float | None:
    """The least-delayed estimate of when the lap actually ended."""
    seen, secs = lap["sector_seen"], lap["sectors_s"]
    candidates = []
    if seen[2] is not None:
        candidates.append(seen[2])
    if seen[1] is not None and secs[2] is not None:
        candidates.append(seen[1] + secs[2])
    if (seen[0] is not None and secs[1] is not None
            and secs[2] is not None):
        candidates.append(seen[0] + secs[1] + secs[2])
    return min(candidates) if candidates else None


def laps_from_stream(records: list) -> dict:
    """``[(t_seconds, patch), ...]`` from the timing stream → per-driver
    lap tables, keyed by car number as the feed writes it.

    Each lap row carries its provenance: ``filled_from_sectors`` marks a
    lap time this module computed rather than received, and ``ended`` is
    the least-delayed end-of-lap estimate (stream seconds), not a value
    the feed ever printed.
    """
    drivers: dict = {}
    for t, patch in records:
        for num, line in (patch.get("Lines") or {}).items():
            if isinstance(line, dict):
                drivers.setdefault(num, _Driver()).apply(t, line)
    return {num: d.table() for num, d in sorted(drivers.items())}
