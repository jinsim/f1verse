"""Tyre-life and deletion logic, without touching the network."""
from f1verse.quality import lap_deletions
from f1verse.strategy import (FUEL_BURN_KG_PER_LAP, FUEL_COST_S_PER_KG,
                              FUEL_START_KG, _trend, circuit_abrasion,
                              fuel_normalised, stint_degradation)


def test_fuel_normalisation_prices_out_the_tank():
    # lap 1 carries the full load; the same raw time later in the race
    # must normalise to a *slower* corrected time
    assert fuel_normalised(90.0, 1) < fuel_normalised(90.0, 40)
    expected = 90.0 - FUEL_COST_S_PER_KG * (FUEL_START_KG
                                            - 9 * FUEL_BURN_KG_PER_LAP)
    assert abs(fuel_normalised(90.0, 10) - expected) < 1e-9


def test_fuel_load_never_goes_negative():
    assert fuel_normalised(90.0, 500) == 90.0


def test_trend_shrugs_off_one_ruined_lap():
    clean = [(l, 90.0 + 0.05 * l) for l in range(1, 10)]
    dirty = clean[:4] + [(5, 97.3)] + clean[5:]   # traffic on lap 5
    assert abs(_trend(dirty) - 0.05) < 0.01


class _StubRace:
    """The smallest object stint analysis needs."""

    def __init__(self):
        self.stints_raw = [
            {"driver_number": 1, "stint_number": 1, "compound": "medium",
             "lap_start": 1, "lap_end": 20, "tyre_age_at_start": 0},
            {"driver_number": 1, "stint_number": 2, "compound": "hard",
             "lap_start": 21, "lap_end": 24, "tyre_age_at_start": 0},
        ]
        self.pits = [{"driver_number": 1, "lap_number": 20}]
        self.laps = [
            {"driver_number": 1, "lap_number": l,
             "lap_duration": 92.0 + 0.06 * l}
            for l in range(1, 25)
        ]

    def interruptions(self):
        return {"sc_vsc_bands": [(10, 11)], "red_flag_laps": []}

    def abbr(self, num):
        return {1: "VER"}[num]


def test_stint_degradation_reports_rate_and_evidence():
    race = _StubRace()
    first, second = stint_degradation(race)
    assert first["driver"] == "VER" and first["compound"] == "MEDIUM"
    # laps 10-12 (VSC band plus the restart lap) and box lap 20 are excluded
    assert first["clean_laps_used"] == 16
    # raw trend is 0.06 s/lap; fuel correction adds 1.6 kg * 0.032 s/kg
    assert abs(first["degradation_s_per_lap"]
               - (0.06 + FUEL_BURN_KG_PER_LAP * FUEL_COST_S_PER_KG)) < 0.01
    # the four-lap final stint is honestly refused, not estimated
    assert second["degradation_s_per_lap"] is None
    assert second["reason"] == "too few clean laps"


def test_circuit_abrasion_declines_to_guess_from_two_stints():
    verdict = circuit_abrasion(_StubRace())
    assert verdict["verdict"] == "unknown" and verdict["factor"] is None


def test_lap_deletions_two_pass():
    messages = [
        {"message": "CAR 4 (NOR) TIME 1:23.456 DELETED - TRACK LIMITS AT "
                    "TURN 4 LAP 12 15:42:01", "date": "2026-06-01T15:42:05"},
        {"message": "CAR 4 (NOR) TIME 1:23.456 REINSTATED", "date": None},
        {"message": "CAR 81 (PIA) TIME 1:24.001 DELETED - TRACK LIMITS",
         "date": None},
        {"message": "YELLOW FLAG SECTOR 7", "date": None},
    ]
    rows = lap_deletions(messages)
    assert len(rows) == 2
    reversed_row = next(r for r in rows if r["car_number"] == 4)
    assert reversed_row["stands"] is False
    assert reversed_row["reason"] == "TRACK LIMITS AT TURN 4 LAP 12"
    assert next(r for r in rows if r["car_number"] == 81)["stands"] is True


def test_running_pace_converges_on_the_stopwatch():
    from f1verse.strategy import _running_pace
    # a tyre modelled at 0.10 s/lap that is actually losing 0.02
    points = [(l, 90.0 + 0.02 * l) for l in range(1, 21)]
    pace, sd = _running_pace(points, expected_rate=0.10)
    assert abs(pace - (90.0 + 0.02 * 20)) < 0.15
    assert sd < 0.3


def test_tyre_outlook_reports_or_declines_with_reasons():
    from f1verse.strategy import tyre_outlook
    rows = tyre_outlook(_StubRace())
    row = rows[0]
    assert row["driver"] == "VER" and row["compound"] == "HARD"
    assert row["pace_now_s"] is None
    assert row["reason"] == "too few clean laps"


def test_strategy_rollout_is_seeded_and_sane():
    from f1verse.predict import strategy_rollout
    candidates = [
        {"name": "one-stop hard", "stints": [
            {"compound": "MEDIUM", "until": 25},
            {"compound": "HARD", "until": 50}]},
        {"name": "no-stop soft", "stints": [
            {"compound": "SOFT", "until": 50}]},
    ]
    a = strategy_rollout(50, 90.0, candidates, runs=400, seed=7)
    b = strategy_rollout(50, 90.0, candidates, runs=400, seed=7)
    assert a == b                                   # same seed, same numbers
    shares = {c["name"]: c["win_share"] for c in a["candidates"]}
    assert abs(sum(shares.values()) - 1.0) < 1e-9
    # fifty laps of soft degradation dwarfs one pit loss
    assert shares["one-stop hard"] > shares["no-stop soft"]
    assert a["assumptions"]["seed"] == 7
