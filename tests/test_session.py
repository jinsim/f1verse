"""Loading the rest of the weekend, not just the race.

The reference weekend (2026 round 12) is a sprint weekend, so it carries
all five session kinds — including the two that break a race-shaped
formatter: qualifying, whose classification is three segment times, and
the sprint, for which OpenF1 publishes no ``/overtakes`` feed.
"""
import json

import pytest

import f1verse
from f1verse.session import Qualifying, Practice


@pytest.fixture(scope="module")
def weekend(race):
    """Reuses the session-scoped cache set up by the ``race`` fixture."""
    return {s["session"]: s for s in f1verse.sessions(2026, 12)}


@pytest.fixture(scope="module")
def sess(race):
    """Every session of the reference weekend, loaded once for the module.

    Each load is seven HTTP round trips at the client's 0.5 s pacing, so
    these are built once and shared rather than per test.
    """
    return {n: f1verse.load_session(2026, 12, n)
            for n in ("Qualifying", "Sprint", "Sprint Qualifying",
                      "Practice 1")}


def test_sessions_lists_the_whole_weekend(weekend):
    assert set(weekend) == {"Practice 1", "Sprint Qualifying", "Sprint",
                            "Qualifying", "Race"}
    assert weekend["Sprint"]["type"] == "Race"
    assert weekend["Sprint Qualifying"]["type"] == "Qualifying"


def test_load_returns_the_class_that_matches_the_session(sess):
    assert isinstance(sess["Qualifying"], Qualifying)
    assert isinstance(sess["Practice 1"], Practice)
    # a sprint is a race: it has a lead, a pace and points
    assert isinstance(sess["Sprint"], f1verse.Race)
    assert isinstance(sess["Sprint Qualifying"], Qualifying)


def test_unknown_session_says_what_the_weekend_had(race):
    with pytest.raises(LookupError) as e:
        f1verse.load_session(2026, 12, "Practice 9")
    assert "Qualifying" in str(e.value) and "Sprint" in str(e.value)


def test_load_is_unchanged_by_the_session_refactor(race):
    assert race.KIND == "Race" and race.name == "Race"
    assert race.laps_led() == {"ANT": 32, "NOR": 31, "HAM": 9}
    assert race.results()[0]["gap"] == "WINNER"


# -- qualifying -------------------------------------------------------------

def test_qualifying_gaps_are_per_segment_not_to_pole(sess):
    q = sess["Qualifying"]
    rows = {r["abbr"]: r for r in q.results()}
    pole = next(r for r in q.results() if r["position"] == 1)
    # the pole-sitter was not fastest in Q1 — the classic reason a single
    # "gap to leader" column is wrong for qualifying
    assert pole["q1_gap"] > 0 and pole["q3_gap"] == 0.0
    assert rows["PIA"]["q1_gap"] == 0.0
    assert pole["best"] == pole["q3"] < pole["q1"]


def test_qualifying_marks_where_each_driver_went_out(sess):
    q = sess["Qualifying"]
    rows = q.results()
    top10 = [r for r in rows if r["eliminated_in"] is None]
    assert len(top10) == 10
    assert all(r["q3"] is not None for r in top10)
    for r in rows:
        if r["eliminated_in"] == "q1":
            assert r["q2"] is None and r["q3"] is None
        if r["eliminated_in"] == "q2":
            assert r["q2"] is not None and r["q3"] is None


def test_segments_report_the_cut_and_its_margin(sess):
    seg = sess["Qualifying"].segments()
    assert set(seg) == {"q1", "q2", "q3"}
    assert len(seg["q2"]["advanced"]) == 10
    assert len(seg["q1"]["eliminated"]) == len(seg["q1"]["ran"]) - len(
        seg["q1"]["advanced"])
    assert seg["q1"]["cut_margin"] > 0
    assert seg["q3"]["advanced"] is None      # the last segment has no cut
    assert seg["q3"]["cut_margin"] is None
    json.dumps(seg)


# -- practice ---------------------------------------------------------------

def test_practice_is_a_best_lap_table(sess):
    p = sess["Practice 1"]
    rows = p.results()
    assert rows[0]["gap"] == "" and rows[0]["best_lap"] is not None
    assert rows[1]["gap"].startswith("+")
    assert rows[0]["best_lap"] < rows[1]["best_lap"]
    assert "points" not in rows[0]


# -- crosscheck degradation -------------------------------------------------

def test_a_sprint_skips_the_check_it_cannot_run(sess):
    cc = sess["Sprint"].crosscheck()
    assert "leader_vs_overtakes" in cc["skipped"]
    assert "leader_vs_overtakes" not in cc["mismatches"]
    assert cc["publishable"] is True          # unavailable ≠ disagreeing


def test_the_race_actually_runs_that_check(race):
    cc = race.crosscheck()
    assert cc["skipped"] == [] and cc["publishable"] is True


# -- quality across kinds ---------------------------------------------------

@pytest.mark.parametrize("name", ["Race", "Qualifying", "Sprint",
                                  "Practice 1"])
def test_quality_report_works_for_every_kind(race, sess, name):
    q = (race if name == "Race" else sess[name]).quality_report()
    assert q["state"] == "final"
    assert q["coverage"]["overall"] > 0.95
    assert q["publishable"] is True
    json.dumps(q)


def test_sector_gaps_do_not_block_publication(sess):
    """Out-laps carry no sector times; that is normal, not a defect."""
    q = sess["Qualifying"].quality_report()
    assert q["coverage"]["sectors"] < 0.95    # would fail a naive gate
    assert q["publishable"] is True
    assert any("sector" in w for w in q["warnings"])


def test_qualifying_is_not_scored_on_the_leader_stream(sess):
    q = sess["Qualifying"].quality_report()
    assert "position_stream" not in q["coverage"]
    assert q["crosscheck"] is None
