# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Surveying a circuit from telemetry, against a synthetic track.

The fixture is a 1 km ellipse carrying a 20 m hill and a DRS zone down one
side, driven by three cars on slightly different lines. Because the track
is known exactly, every derived number can be checked against the truth
rather than merely asserted to exist.
"""
import math
from datetime import datetime, timedelta, timezone

import pytest

from f1verse import survey

RADIUS_X, RADIUS_Y = 200.0, 120.0     # metres
HILL_M = 20.0
DRS_FROM, DRS_TO = 0.30, 0.45         # fraction of the lap
SAMPLES = 400
START = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)


def _car(offset_m: float, number: int) -> list:
    """One lap of position rows, driven ``offset_m`` off the centre line."""
    rows = []
    for i in range(SAMPLES):
        angle = 2 * math.pi * i / SAMPLES
        # outward normal of the ellipse, near enough for a fixed offset
        nx, ny = math.cos(angle), math.sin(angle)
        length = math.hypot(nx, ny)
        x = (RADIUS_X + offset_m) * math.cos(angle)
        y = (RADIUS_Y + offset_m * ny / length) * math.sin(angle)
        z = HILL_M * (1 - math.cos(angle)) / 2
        rows.append({
            "date": (START + timedelta(seconds=i * 0.25)).isoformat(),
            # the feed reports tenths of a metre
            "x": x * 10, "y": y * 10, "z": z * 10,
            "driver_number": number,
        })
    return rows


def _drs(number: int) -> list:
    rows = []
    for i in range(SAMPLES):
        share = i / SAMPLES
        rows.append({
            "date": (START + timedelta(seconds=i * 0.25)).isoformat(),
            "drs": 12 if DRS_FROM <= share < DRS_TO else 1,
            "driver_number": number,
        })
    return rows


class _Race:
    year, round, name = 2026, 12, "Race"
    session_key = 1

    def __init__(self, lines=(0.0, 3.0, -3.0)):
        self._lines = dict(zip((1, 44, 16), lines))
        self.laps = [{"driver_number": n, "lap_number": 1,
                      "lap_duration": 100.0 + i,
                      "date_start": START.isoformat()}
                     for i, n in enumerate(self._lines)]

    def abbr(self, number):
        return {1: "VER", 44: "HAM", 16: "LEC"}[number]


@pytest.fixture
def race(monkeypatch):
    fixture = _Race()

    def _get(endpoint, **params):
        number = params["driver_number"]
        if endpoint == "location":
            return _car(fixture._lines[number], number)
        if endpoint == "car_data":
            rows = _drs(number)
            # the whole-session scan asks the feed for open wings only
            if "drs>=" in params:
                return [r for r in rows if r["drs"] >= params["drs>="]]
            return rows
        raise AssertionError(f"unexpected endpoint {endpoint}")

    monkeypatch.setattr(survey.openf1, "get", _get)
    return fixture


def test_elevation_recovers_the_hill(race):
    profile = survey.elevation(race)
    assert profile["available"] is True
    # a 20 m hill, measured to within a few centimetres
    assert abs(profile["total_rise_m"] - HILL_M) < 0.5
    assert profile["datum"] == "lowest point of this circuit"
    assert len(profile["stations"]) == 100
    # the profile is a single climb and a single descent, so the steepest
    # of each must have opposite signs
    assert profile["steepest_climb_percent"] > 0
    assert profile["steepest_descent_percent"] < 0


def test_elevation_measures_a_believable_lap_length(race):
    # Ramanujan's approximation for the perimeter of this ellipse
    a, b = RADIUS_X, RADIUS_Y
    h = (a - b) ** 2 / (a + b) ** 2
    expected = math.pi * (a + b) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))
    assert abs(survey.elevation(race)["lap_distance_m"] - expected) < 5


def test_elevation_declines_without_a_height_channel(race, monkeypatch):
    flat = [dict(row, z=None) for row in _car(0.0, 1)]
    monkeypatch.setattr(survey.openf1, "get",
                        lambda endpoint, **_: flat if endpoint == "location"
                        else [])
    profile = survey.elevation(race)
    assert profile["available"] is False
    assert "height channel" in profile["reason"]


def test_drs_zone_is_found_where_the_wings_open(race):
    found = survey.drs_zones(race)
    assert found["available"] is True
    assert len(found["zones"]) == 1
    zone = found["zones"][0]
    lap = found["lap_distance_m"]
    # the synthetic zone covers 30%-45% of the lap
    assert abs(zone["start_m"] / lap - DRS_FROM) < 0.05
    assert abs(zone["end_m"] / lap - DRS_TO) < 0.05
    # every car that ran is evidence for it
    assert zone["drivers_observed"] == ["HAM", "LEC", "VER"]


def test_drs_reports_absence_rather_than_inventing_a_zone(race, monkeypatch):
    real = survey.openf1.get
    monkeypatch.setattr(survey.openf1, "get",
                        lambda endpoint, **kw: (
                            [dict(r, drs=1) for r in real(endpoint, **kw)]
                            if endpoint == "car_data" else real(endpoint, **kw)))
    found = survey.drs_zones(race)
    assert found["available"] is False
    assert "no DRS activation" in found["reason"]


def test_corridor_measures_the_spread_between_lines(race):
    band = survey.driven_corridor(race)
    assert band["available"] is True
    assert band["drivers_measured"] == 3
    # lines sit at -3 m, 0 m and +3 m, so the band is about 6 m wide
    assert 4.0 < band["widest_m"] < 9.0
    assert "lower bound" in band["measurement"]


def test_corridor_needs_more_than_one_lap(race, monkeypatch):
    monkeypatch.setattr(race, "laps", race.laps[:1])
    band = survey.driven_corridor(race)
    assert band["available"] is False
    assert band["drivers_measured"] == 1


def test_survey_composes_all_three_with_provenance(race):
    whole = survey.survey(race)
    assert whole["elevation"]["available"] is True
    assert whole["drs_zones"]["available"] is True
    assert whole["driven_corridor"]["available"] is True
    # the stub circuit publishes no corner numbering, and that is reported
    # rather than raised
    assert whole["corners"]["available"] is False
    assert whole["event"]["round"] == 12
    assert "no external geometry service" in whole["note"]


def test_character_reads_the_lap_a_car_drove(race, monkeypatch):
    def _get(endpoint, **params):
        number = params["driver_number"]
        if endpoint == "location":
            return _car(fixture_lines[number], number)
        # flat out on the DRS side of the lap, braking on the far side
        rows = []
        for i in range(SAMPLES):
            share = i / SAMPLES
            flat = DRS_FROM <= share < DRS_TO
            rows.append({
                "date": (START + timedelta(seconds=i * 0.25)).isoformat(),
                "throttle": 100 if flat else 40,
                "brake": 0 if flat else (100 if 0.6 <= share < 0.7 else 0),
                "speed": 320 if flat else (120 if 0.6 <= share < 0.7 else 200),
                "drs": 12 if flat else 1, "driver_number": number})
        if "drs>=" in params:
            return [r for r in rows if r["drs"] >= params["drs>="]]
        return rows

    fixture_lines = {1: 0.0, 44: 3.0, 16: -3.0}
    monkeypatch.setattr(survey.openf1, "get", _get)
    shape = survey.character(race)
    assert shape["available"] is True
    # the flat-out stretch is 15% of the lap by design
    assert 10 < shape["full_throttle_percent"] < 20
    assert shape["top_speed_kph"] == 320
    assert shape["braking_zones"] == 1
    hardest = shape["hardest_braking_zone"]
    assert hardest["entry_kph"] == 200 and hardest["min_kph"] == 120
    assert hardest["speed_shed_kph"] == 80


def test_overtaking_zones_cluster_and_wrap_the_start_line(race, monkeypatch):
    real = survey.openf1.get
    # passes either side of the timing line are one zone, not two
    shares = [0.985, 0.99, 0.995, 0.002, 0.008, 0.5]
    passes = [{"date": (START + timedelta(seconds=100.0 * s)).isoformat(),
               "overtaking_driver_number": 44, "overtaken_driver_number": 16,
               "position": 3} for s in shares]
    monkeypatch.setattr(survey.openf1, "get",
                        lambda endpoint, **kw: passes
                        if endpoint == "overtakes" else real(endpoint, **kw))
    found = survey.overtaking_zones(race, min_passes=2)
    assert found["available"] is True
    assert found["passes_located"] == len(shares)
    busiest = found["zones"][0]
    assert busiest["passes"] == 5          # the lone mid-lap pass is separate
    assert busiest["crosses_start_line"] is True


def test_overtaking_declines_without_a_feed(race, monkeypatch):
    real = survey.openf1.get

    def _get(endpoint, **kw):
        if endpoint == "overtakes":
            raise LookupError("404")
        return real(endpoint, **kw)

    monkeypatch.setattr(survey.openf1, "get", _get)
    found = survey.overtaking_zones(race)
    assert found["available"] is False
    assert "no overtake feed" in found["reason"]


def test_circle_fit_recovers_a_known_radius():
    from f1verse.survey import _fit_radius
    for truth in (35.0, 120.0, 480.0):
        arc = [(truth * math.cos(a / 40), truth * math.sin(a / 40) + 7.0)
               for a in range(12)]
        assert abs(_fit_radius(arc) - truth) < truth * 0.02


def test_circle_fit_declines_on_a_straight():
    from f1verse.survey import _fit_radius
    assert _fit_radius([(x * 10.0, 5.0) for x in range(12)]) is None


def test_circle_fit_needs_enough_of_an_arc():
    from f1verse.survey import _fit_radius
    assert _fit_radius([(0.0, 0.0), (1.0, 1.0), (2.0, 3.0)]) is None


def test_lateral_load_is_physics_not_a_fit():
    # a car at 216 km/h (60 m/s) on a 120 m radius holds 60^2/120 = 30
    # m/s^2, which is a shade over three g
    from f1verse.survey import _fit_radius
    radius = _fit_radius([(120.0 * math.cos(a / 30), 120.0 * math.sin(a / 30))
                          for a in range(12)])
    assert abs((216 / 3.6) ** 2 / radius / 9.81 - 3.06) < 0.1
