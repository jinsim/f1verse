# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Regression tests against a known race.

Every expected value here was verified by hand against the published
classification. If a change breaks one of these, the change is wrong until
proven otherwise.

The 2026 Dutch Grand Prix is the reference because it exercises the awkward
cases in one race: a red flag, two VSC periods, six retirements, lapped
finishers, and a winner who did *not* lead the most laps.

Network-backed: results are cached after the first run.
"""
import json

import pytest

import f1verse

YEAR, ROUND = 2026, 12


def test_event_identity(race):
    story = race.story()
    assert "Dutch" in story["event"]["name"]
    assert story["event"]["total_laps"] == 72


def test_laps_led_winner_is_not_the_leader(race):
    """The winner led 31 laps; the runner-up led 32. A summary that assumes
    'winner == most laps led' is wrong, and this race proves it."""
    assert race.laps_led() == {"ANT": 32, "NOR": 31, "HAM": 9}


def test_leader_runs_are_contiguous_and_complete(race):
    runs = race.leader_runs()
    assert len(runs) == 7
    assert runs[0]["from"] == 1
    assert runs[-1]["to"] == 72
    for prev, nxt in zip(runs, runs[1:]):
        assert nxt["from"] == prev["to"] + 1     # no gaps, no overlaps
        assert nxt["abbr"] != prev["abbr"]       # a run is one driver


@pytest.mark.parametrize("abbr,expected", [
    ("NOR", "WINNER"),      # race winner
    ("LAW", "+1:19.915"),   # over a minute back, still on the lead lap
    ("HUL", "+1 LAP"),      # lapped — must never print a raw interval
    ("VER", "DNF"),         # retired
])
def test_gap_formatting(race, abbr, expected):
    gaps = {r["abbr"]: r["gap"] for r in race.results()}
    assert gaps[abbr] == expected


def test_lapped_car_is_not_shown_ahead_of_a_slower_finisher(race):
    """The raw classified time for a lapped car can be smaller than that of
    a car classified ahead of it. Formatted output must not reproduce that."""
    rows = [r for r in race.results() if r["position"] in (7, 8)]
    p7, p8 = sorted(rows, key=lambda r: r["position"])
    assert p7["gap"].startswith("+") and "LAP" not in p7["gap"]
    assert p8["gap"] == "+1 LAP"


def test_interruptions(race):
    inter = race.interruptions()
    assert inter["sc_vsc_bands"] == [[55, 57], [70, 70]]
    assert inter["red_flag_laps"] == [2]


def test_race_pace_excludes_neutralised_laps(race):
    pace = race.race_pace()
    assert list(pace)[0] == "ANT"
    assert pace["ANT"] == pytest.approx(76.195, abs=0.05)
    # every driver's median must be a plausible green-flag lap, not an
    # average dragged upwards by safety-car laps
    assert all(70 < v < 90 for v in pace.values())


def test_timeline_is_ordered_and_covers_the_race(race):
    events = race.timeline()
    assert events
    assert events == sorted(events, key=lambda e: e["lap"])
    assert {e["kind"] for e in events} >= {"out", "red", "sc", "lead"}
    assert sum(e["kind"] == "out" for e in events) == 6   # six retirements


def test_crosscheck_passes(race):
    report = race.crosscheck()
    assert report["publishable"], report["mismatches"]
    assert len(report["checks"]) >= 6


def test_story_is_json_serialisable(race):
    """Web and video pipelines consume this directly — numpy scalars or
    timestamps leaking through would break them at the last step."""
    json.dumps(race.story())


def test_weather_summary(race):
    w = f1verse.weather_summary(race)
    assert w["samples"] > 100
    assert 20 < w["track_c"]["min"] < w["track_c"]["max"] < 60
    assert w["air_c"]["min"] < w["track_c"]["min"]   # track runs hotter


def test_lap_telemetry_is_bounded_and_plausible(race):
    """A lap's telemetry must cover one lap, not the whole session."""
    samples = f1verse.lap_telemetry(race, "NOR", 40)
    assert 100 < len(samples) < 1000
    assert 250 < max(s["speed"] for s in samples) < 400
    assert max(s["gear"] for s in samples) <= 8


def test_lap_trace_returns_coordinates(race):
    trace = f1verse.lap_trace(race, "NOR", 40)
    assert len(trace) > 100
    assert all(p["x"] is not None and p["y"] is not None for p in trace)
