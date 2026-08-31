# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Championship projection mechanics, without touching the network."""
import pytest

from f1verse.predict import (RACE_POINTS, SPRINT_POINTS, _order_from_draws,
                             championship_projection)


class _Rng:
    """Deterministic stand-in: random() walks a fixed cycle."""

    def __init__(self, vals):
        self.vals, self.i = vals, 0

    def random(self):
        v = self.vals[self.i % len(self.vals)]
        self.i += 1
        return v


def test_points_tables_match_the_regulations():
    assert RACE_POINTS[1] == 25 and RACE_POINTS[10] == 1
    assert sum(RACE_POINTS.values()) == 101        # a full race, all scorers
    assert SPRINT_POINTS[1] == 8 and SPRINT_POINTS[8] == 1
    assert 11 not in RACE_POINTS and 9 not in SPRINT_POINTS


def test_draws_become_one_valid_finishing_order():
    order = _order_from_draws({"A": 1, "B": 2, "C": 3}, _Rng([0.1, 0.2, 0.3]))
    assert order == ["A", "B", "C"]
    # every driver appears exactly once — no simulated race has two winners
    assert sorted(order) == ["A", "B", "C"]


def test_equal_draws_are_broken_without_dropping_anyone():
    order = _order_from_draws({"A": 4, "B": 4, "C": 4}, _Rng([0.9, 0.1, 0.5]))
    assert sorted(order) == ["A", "B", "C"]
    assert order[0] == "B"            # smallest jitter wins the tie


def test_a_finished_season_reports_the_champion_not_a_probability(monkeypatch):
    import f1verse.predict as P
    monkeypatch.setattr(P, "_standings_at",
                        lambda y, a: ([{"position": 1, "name": "VER",
                                        "points": 400.0, "wins": 15}], 24))
    monkeypatch.setattr(P, "remaining_rounds", lambda y, r: [])
    out = championship_projection(2023)
    assert out["settled"] is True and out["champion"] == "VER"
    assert "drivers" not in out


def _stub(monkeypatch, rows, rounds, form):
    import f1verse.predict as P
    monkeypatch.setattr(P, "_standings_at", lambda y, a: (rows, 12))
    monkeypatch.setattr(P, "remaining_rounds", lambda y, r: rounds)
    monkeypatch.setattr(P, "_season_form", lambda y, r: form)


def test_a_runaway_leader_is_near_certain_and_the_run_is_reproducible(monkeypatch):
    rows = [{"position": 1, "name": "AAA", "points": 300.0, "wins": 10},
            {"position": 2, "name": "BBB", "points": 100.0, "wins": 0}]
    form = {"AAA": {"finishes": [1, 1, 1, 2], "started": 4, "retired": 0,
                    "dnf_rate": 0.0},
            "BBB": {"finishes": [3, 4, 5, 6], "started": 4, "retired": 0,
                    "dnf_rate": 0.0}}
    _stub(monkeypatch, rows, [{"round": 13, "name": "X", "sprint": False}], form)
    a = championship_projection(2026, runs=300, seed=5)
    b = championship_projection(2026, runs=300, seed=5)
    assert a == b                                   # same seed, same numbers
    lead = next(d for d in a["drivers"] if d["driver"] == "AAA")
    assert lead["title_probability"] > 0.99
    assert abs(sum(d["title_probability"] for d in a["drivers"]) - 1.0) < 1e-9


def test_probabilities_carry_their_evidence(monkeypatch):
    rows = [{"position": 1, "name": "AAA", "points": 200.0, "wins": 5},
            {"position": 2, "name": "BBB", "points": 190.0, "wins": 4}]
    form = {"AAA": {"finishes": [1, 2, 3, 4, 5], "started": 6, "retired": 1,
                    "dnf_rate": 0.167},
            "BBB": {"finishes": [1, 2, 3, 4, 5], "started": 5, "retired": 0,
                    "dnf_rate": 0.0}}
    _stub(monkeypatch, rows, [{"round": 13, "name": "X", "sprint": True}], form)
    out = championship_projection(2026, runs=200, seed=3)
    row = out["drivers"][0]
    for field in ("races_in_sample", "measured_dnf_rate",
                  "projected_points_p10", "projected_points_p90"):
        assert field in row
    assert out["assumptions"]["seed"] == 3
    assert out["sprints_left"] == 1
    # the ignored factors are stated, not implied
    assert "car development" in out["assumptions"]["ignores"]


def test_a_driver_with_too_few_races_is_named_rather_than_zeroed(monkeypatch):
    rows = [{"position": 1, "name": "AAA", "points": 200.0, "wins": 5},
            {"position": 2, "name": "NEW", "points": 4.0, "wins": 0}]
    form = {"AAA": {"finishes": [1, 1, 2, 3], "started": 4, "retired": 0,
                    "dnf_rate": 0.0},
            "NEW": {"finishes": [12], "started": 1, "retired": 0,
                    "dnf_rate": 0.0}}
    _stub(monkeypatch, rows, [{"round": 13, "name": "X", "sprint": False}], form)
    out = championship_projection(2026, runs=100, seed=1, min_races=3)
    assert out["not_modelled"] == ["NEW"]
    assert all(d["driver"] != "NEW" for d in out["drivers"])
