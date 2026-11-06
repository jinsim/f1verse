# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Known-answer experiments for descriptive methods and forecast evaluation."""
import json
import math

import pytest

import f1verse
from f1verse import predict
from f1verse.events import _stamp
from f1verse.evaluation import forecast_scores
from f1verse.reliability import retirement_risk
from f1verse.strategy import pace_changes, stint_degradation


class RaceSample:
    year, round, name, lifecycle, session_key = 2026, 1, "Race", "final", 11

    def __init__(self, shift=0, boundary=None):
        self.laps = [{"driver_number": 1, "lap_number": l,
                      "lap_duration": 90 + 0.03 * l + (shift if l >= 16 else 0)}
                     for l in range(1, 31) if l != boundary]
        self.stints_raw = [{"driver_number": 1, "stint_number": 1, "compound": "HARD",
                            "lap_start": 1, "lap_end": 30}]
        self.pits = []
        self.result = [{"driver_number": 1, "number_of_laps": 10, "dnf": True},
                       {"driver_number": 2, "number_of_laps": 20, "dnf": False}]

    def interruptions(self):
        return {"sc_vsc_bands": [], "red_flag_laps": []}

    def abbr(self, num):
        return {1: "AAA", 2: "BBB"}[num]


def test_modern_fuel_is_not_invented_but_raw_trend_remains_available():
    row, = stint_degradation(RaceSample())
    assert row["degradation_s_per_lap"] is None
    assert row["raw_trend_s_per_lap"] == pytest.approx(0.03)
    assert row["fuel_model"]["scope"] == "unsupported_era"
    scenario = {"start_kg": 50, "burn_kg_per_lap": 1, "cost_s_per_kg": 0.02}
    row, = stint_degradation(RaceSample(), fuel_model=scenario)
    assert row["degradation_s_per_lap"] == pytest.approx(0.05)
    assert row["fuel_model"]["scope"] == "caller_scenario"
    json.dumps(row, allow_nan=False)


def test_pace_shift_detector_distinguishes_trend_step_and_missing_boundary():
    assert not pace_changes(RaceSample())["changes"]
    report = pace_changes(RaceSample(shift=2))
    change, = report["changes"]
    assert change["lap"] == 16
    assert change["shift_s"] == pytest.approx(2)
    assert change["cause"] is None
    assert report["uses_future_information"]
    assert not pace_changes(RaceSample(shift=2, boundary=15))["changes"]


def test_one_outlier_is_not_a_persistent_shift():
    race = RaceSample()
    race.laps[14]["lap_duration"] += 3
    assert pace_changes(race)["changes"] == []


def test_null_signal_false_positives_on_known_noise_are_bounded():
    import random
    rng = random.Random(13)
    false_positives = 0
    for _ in range(100):
        race = RaceSample()
        for lap in race.laps:
            lap["lap_duration"] += rng.gauss(0, 0.1)
        false_positives += bool(pace_changes(race)["changes"])
    assert false_positives <= 5  # specified synthetic noise, not a real-data guarantee


def test_public_event_report_is_computation_only_and_preserves_lineage(monkeypatch):
    from f1verse.race import Race
    from f1verse import http
    def forbidden(*args, **kwargs):
        raise AssertionError("event construction must not fetch sources")
    monkeypatch.setattr(http, "_fetch", forbidden)
    race = object.__new__(Race)
    race.year, race.round, race.name, race.session_key = 2026, 1, "Race", 12
    race.info = {"date_end": "2020-01-01T12:00:00+00:00"}
    race.drivers = {1: {"name_acronym": "AAA"}}
    race.laps = [{"lap_number": l, "driver_number": 1, "lap_duration": 90,
                  "date_start": f"2020-01-01T00:0{l}:00+00:00"} for l in range(1, 5)]
    race.result = [{"driver_number": 1, "dnf": False}]
    race.total_laps, race._p1, race.race_control, race.stints_raw = 4, [], [], []
    race.pits = [{"lap_number": 2, "driver_number": 1}]
    report = race.events()
    pit, = report["events"]
    assert pit["kind"] == "pit" and pit["evidence"][0]["endpoint"] == "pit"
    assert race.turning_points()["events"][0]["event_id"] == pit["event_id"]
    json.dumps(report, allow_nan=False)


def test_event_identity_is_stable_but_revisions_change_with_evidence():
    race = RaceSample()
    rows = [{"lap": 2, "kind": "lead", "abbr": "AAA", "over": "BBB", "title": "lead"},
            {"lap": 3, "kind": "out", "abbr": "BBB", "title": "out"}]
    a = _stamp(race, rows)
    assert _stamp(race, list(reversed(rows)) + [rows[0]]) == a
    changed = _stamp(race, [{**rows[0], "title": "corrected"}])[0]
    assert changed["event_id"] == a[0]["event_id"]
    assert changed["revision"] != a[0]["revision"]
    conflicted = _stamp(race, [rows[0], {**rows[0], "title": "corrected"}])[0]
    assert len(conflicted["conflicting_revisions"]) == 2


def test_completed_races_are_censored_and_duplicate_sessions_do_not_inflate_sample():
    race = RaceSample()
    report = retirement_risk([race, race])
    assert report["starts"] == 2
    first, last = report["curve"]
    assert first["survival"] == 0.5 and first["at_risk"] == 2
    assert last["survival"] == 0.5 and last["censored"] == 1
    race.lifecycle = "in_progress"
    assert retirement_risk([race])["starts"] == 0


def test_proper_scores_penalize_confident_wrong_predictions():
    good = forecast_scores([{"probabilities": {"A": 0.8, "B": 0.2}, "actual": "A"}])
    bad = forecast_scores([{"probabilities": {"A": 0.2, "B": 0.8}, "actual": "A"}])
    assert good["brier"] == pytest.approx(0.08)
    assert good["log_loss"] == pytest.approx(-math.log(0.8))
    assert bad["brier"] > good["brier"] and bad["log_loss"] > good["log_loss"]
    assert forecast_scores([])["brier"] is None
    assert forecast_scores([{"probabilities": {"A": 1}, "actual": "B"}])["skipped"]


def test_rolling_backtest_keeps_failed_cases_and_scores_only_held_out_outcomes(monkeypatch):
    import f1verse.history as history
    monkeypatch.setattr(history, "standings", lambda y: {"standings": [
        {"name": "AAA", "points": 300}, {"name": "BBB", "points": 200}]})
    seen = []
    def project(year, **kwargs):
        cutoff = kwargs["as_of"]
        seen.append((year, cutoff))
        if year == 2021:
            raise RuntimeError("unavailable")
        return {"drivers": [
            {"driver": "AAA", "title_probability": 0.8, "projected_points_p10": 270,
             "projected_points_p90": 330},
            {"driver": "BBB", "title_probability": 0.2, "projected_points_p10": 170,
             "projected_points_p90": 230}]}
    monkeypatch.setattr(predict, "championship_projection", project)
    out = predict.backtest_projection(2020, 2021, checkpoints=[4, 8])
    assert seen == [(2020, 4), (2020, 8), (2021, 4), (2021, 8)]
    assert out["forecasts_tested"] == 2 and out["seasons_tested"] == 1
    assert len(out["excluded"]) == 2
    assert out["scores"]["brier"] < out["uniform_baseline"]["brier"]
    assert out["points_interval"]["observed_coverage"] == 1
    assert "dependent" in out["note"]


def test_scenario_arithmetic_includes_historical_fastest_lap_and_sprint_rules(monkeypatch):
    monkeypatch.setattr(predict, "_standings_at", lambda y, r: (
        [{"name": "AAA", "points": 100}, {"name": "BBB", "points": 68}], 12))
    monkeypatch.setattr(predict, "remaining_rounds", lambda y, r: [{"round": 13, "sprint": True}])
    assert predict.title_scenarios(2021)["max_points_available"] == 29
    assert predict.title_scenarios(2024)["max_points_available"] == 34
    assert predict.title_scenarios(2026)["max_points_available"] == 33


def test_tool_validation_happens_before_any_network_access():
    with pytest.raises(TypeError, match="integer"):
        f1verse.call_tool("f1_race_story", {"year": True, "round": 1})
    with pytest.raises(ValueError):
        f1verse.call_tool("f1_retirement_risk", {"year": 2026, "rounds": []})
    assert f1verse.call_tool("f1_source_status", {})["sources"]


def test_strategy_scenarios_cannot_win_by_omitting_the_end_of_the_race():
    from f1verse.predict import strategy_rollout
    with pytest.raises(ValueError, match="total_laps"):
        strategy_rollout(50, 90, [{"name": "short", "stints": [{"until": 20}]}])
    with pytest.raises(ValueError, match="name"):
        strategy_rollout(50, 90, [{"stints": []}])


def test_modern_telemetry_never_turns_the_old_drs_channel_into_new_modes():
    from f1verse.telemetry import _aero
    row = _aero(RaceSample(), {"drs": 12})
    assert row["drs_open"] is None and row["drs_status"] == "not_applicable"
    assert row["overtake_mode"] is None and row["boost_mode"] is None
