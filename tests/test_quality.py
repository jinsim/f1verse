# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Quality layer: revision journal, lifecycle, coverage, snapshot/diff.

Everything except the reference-race block runs offline — the journal is
exercised over ``file://`` URLs so a correction can actually be staged.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

import f1verse
from f1verse import http, schedule
from f1verse.sources import openf1


@pytest.fixture
def cache(tmp_path):
    """Isolated cache dir, restored afterwards — the session-scoped ``race``
    fixture shares the same module-level setting."""
    previous = http._cache_dir
    f1verse.enable_cache(str(tmp_path / "cache"))
    yield tmp_path
    http._cache_dir = previous


# -- revision journal -------------------------------------------------------

def test_revision_is_journalled_with_the_superseded_body(cache):
    src = cache / "result.json"
    src.write_text(json.dumps([{"position": 1, "driver": "HAM"}]))
    url = src.as_uri()

    assert http.get_json(url, ttl=0)[0]["position"] == 1
    assert http.revisions() == []                    # nothing changed yet

    src.write_text(json.dumps([{"position": None, "driver": "HAM"}]))
    assert http.get_json(url, ttl=0)[0]["position"] is None

    recs = http.revisions()
    assert len(recs) == 1
    r = recs[0]
    assert r["url"] == url
    assert r["previous_sha256"] != r["current_sha256"]
    assert (r["rows_added"], r["rows_removed"]) == (1, 1)
    assert http.vintage(r) == [{"position": 1, "driver": "HAM"}]


def test_unchanged_refetch_is_not_a_revision(cache):
    src = cache / "same.json"
    src.write_text('[{"a": 1}]')
    url = src.as_uri()
    http.get_json(url, ttl=0)
    http.get_json(url, ttl=0)
    assert http.revisions() == []


def test_clear_cache_keeps_the_record_of_what_changed(cache):
    src = cache / "r.json"
    src.write_text('[{"a": 1}]')
    url = src.as_uri()
    http.get_json(url, ttl=0)
    src.write_text('[{"a": 2}]')
    http.get_json(url, ttl=0)

    assert f1verse.cache_info()["revisions"] == 1
    f1verse.clear_cache()
    assert len(f1verse.revisions()) == 1              # journal survives
    assert f1verse.vintage(f1verse.revisions()[0]) == [{"a": 1}]
    assert f1verse.cache_info()["entries"] == 0


# -- lifecycle --------------------------------------------------------------

def test_lifecycle_walks_provisional_to_final():
    end = datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc)
    at = lambda **kw: schedule.lifecycle(end, now=end + timedelta(**kw))
    assert at(minutes=-5) == "in_progress"
    assert at(minutes=10) == "provisional"
    assert at(minutes=schedule.SETTLE_MINUTES + 1) == "settled"
    assert at(hours=schedule.FINAL_HOURS + 1) == "final"


def test_lifecycle_accepts_an_iso_string():
    assert schedule.lifecycle(
        "2020-01-01T00:00:00+00:00") == "final"


# -- diff -------------------------------------------------------------------

def _snap(rows, **kw):
    d = {"schema_version": f1verse.SCHEMA_VERSION, "results": rows,
         "sha256": "x", "taken_at": "2026-08-23T17:00:00Z", "state": "settled"}
    d.update(kw)
    return d


def test_diff_reports_a_disqualification_as_changed_fields():
    before = _snap([{"abbr": "HAM", "position": 4, "points": 12.0, "gap": "+8.1s"},
                    {"abbr": "LEC", "position": 5, "points": 10.0, "gap": "+9.4s"}])
    after = _snap([{"abbr": "HAM", "position": None, "points": 0.0, "gap": "DSQ"},
                   {"abbr": "LEC", "position": 4, "points": 12.0, "gap": "+9.4s"}],
                  state="corrected")
    d = f1verse.diff(before, after)
    assert d["changed"] is True
    fields = {(c["abbr"], c["field"]) for c in d["changes"]}
    assert ("HAM", "position") in fields and ("HAM", "gap") in fields
    assert ("LEC", "position") in fields
    assert d["added"] == [] and d["removed"] == []
    assert d["to"]["state"] == "corrected"
    assert json.dumps(d)                     # JSON-safe


def test_diff_of_an_unchanged_classification_is_quiet():
    rows = [{"abbr": "NOR", "position": 1, "points": 25.0, "gap": "WINNER"}]
    d = f1verse.diff(_snap(rows), _snap(rows))
    assert d["changed"] is False and d["changes"] == []


# -- reference race ---------------------------------------------------------

def test_quality_report_on_the_reference_race(race):
    q = race.quality_report()
    assert q["schema_version"] == f1verse.SCHEMA_VERSION
    assert q["state"] == q["lifecycle"] == "final"   # long settled
    assert q["session"]["session_key"] == race.session_key
    assert q["coverage"]["overall"] > 0.95
    assert q["coverage"]["laps"] <= 1.0               # never over-complete
    assert q["publishable"] is True
    assert q["crosscheck"]["publishable"] is True
    assert q["source_age_seconds"] is not None
    assert set(q["provenance"]) >= {"laps", "session_result", "stints", "pit"}
    assert q["provenance"]["session_result"]["revisable"] is True
    assert q["provenance"]["laps"]["revisable"] is False
    json.dumps(q)


def test_missing_names_the_field_it_could_not_find(race):
    q = race.quality_report()
    for name in q["missing"]:
        drv, lap, field = name.split(".")
        assert lap.startswith("lap_")
        assert field.startswith("sector_") or field == "lap_duration"
    assert sum(q["missing_counts"].values()) >= len(q["missing"])


def test_snapshot_is_stable_and_diffs_against_itself(race):
    a, b = race.snapshot(), race.snapshot()
    assert a["sha256"] == b["sha256"]        # hash covers rows, not the clock
    assert len(a["results"]) == len(race.results())
    assert f1verse.diff(a, b)["changed"] is False


def test_story_declares_its_contract_version(race):
    s = race.story()
    assert s["schema_version"] == f1verse.SCHEMA_VERSION
    assert s["state"] == "final"


# -- revisable rows are not cached forever until the session is final -------

def test_provisional_sessions_recheck_the_rows_stewards_can_rewrite(
        race, monkeypatch):
    """The bug this guards: a disqualification landing after a result was
    first fetched is invisible if the row was cached forever at the flag."""
    seen = {}
    real = openf1.get

    def spy(endpoint, ttl="auto", **params):
        seen[endpoint] = ttl
        return real(endpoint, ttl="auto", **params)

    monkeypatch.setattr(openf1, "get", spy)
    monkeypatch.setattr(type(race), "lifecycle",
                        property(lambda self: "settled"))
    race._load()

    for ep in ("session_result", "race_control", "stints", "pit"):
        assert seen[ep] == http.TTL_PROVISIONAL, ep
    assert seen["laps"] == "auto"          # lap times are genuinely immutable


def test_final_sessions_stop_rechecking(race, monkeypatch):
    seen = {}
    real = openf1.get

    def spy(endpoint, ttl="auto", **params):
        seen[endpoint] = ttl
        return real(endpoint, ttl="auto", **params)

    monkeypatch.setattr(openf1, "get", spy)
    race._load()                            # the reference race is long final
    assert seen["session_result"] is http.TTL_FOREVER


def test_refresh_forces_a_refetch(race, monkeypatch):
    seen = {}
    real = openf1.get

    def spy(endpoint, ttl="auto", **params):
        seen[endpoint] = ttl
        return real(endpoint, ttl="auto", **params)

    monkeypatch.setattr(openf1, "get", spy)
    assert race.refresh() is race
    assert seen["session_result"] == 0
