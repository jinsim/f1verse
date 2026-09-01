# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Published circuit facts and the audit that checks them, offline."""
from f1verse import reference


def test_a_recorded_circuit_carries_its_provenance():
    entry = reference.facts("Zandvoort")
    assert entry["length_m"] == 4259 and entry["corners"] == 14
    # a fact without a source is not a fact this library will keep
    assert entry["source"] and entry["checked"]


def test_an_unchecked_circuit_says_so_rather_than_guessing():
    assert reference.facts("Kyalami") is None   # no curated entry, no article
    assert "Zandvoort" in reference.known()


def test_audit_accepts_a_measurement_within_tolerance():
    result = reference.audit("Zandvoort", {"lap_distance_m": 4274.4,
                                           "corners": 14})
    assert result["verdict"] == "agrees"
    length = next(c for c in result["checks"] if c["field"] == "length_m")
    assert length["off_by_percent"] == 0.36


def test_audit_flags_a_figure_that_has_gone_stale():
    # a shortened layout the table has not caught up with
    result = reference.audit("Zandvoort", {"lap_distance_m": 3900.0,
                                           "corners": 12})
    assert result["verdict"] == "differs"
    assert {c["field"] for c in result["checks"]
            if c["state"] == "differs"} == {"length_m", "corners"}
    # it reports a disagreement, not a culprit
    assert "not a culprit" in result["note"]


def test_audit_without_a_reference_is_not_a_pass():
    result = reference.audit("Nowhere Park", {"lap_distance_m": 1.0})
    assert result["verdict"] == "no reference"


def test_a_missing_measurement_is_unchecked_not_agreed():
    result = reference.audit("Zandvoort", {"lap_distance_m": None,
                                           "corners": None})
    assert result["verdict"] == "unchecked"
    assert all(c["state"] == "unchecked" for c in result["checks"])


class _Wikidata:
    """A stand-in for the upstream, so these tests stay offline."""

    def __init__(self, **facts):
        self.facts = {"available": True, "wikidata_id": "Q1",
                      "source": "Wikidata Q1 (CC0)", **facts}
        self.asked = []

    def circuit_facts(self, url):
        self.asked.append(url)
        return self.facts


def _patch(monkeypatch, stub):
    import f1verse.sources as sources
    monkeypatch.setattr(sources, "wikidata", stub, raising=False)
    import sys
    monkeypatch.setitem(sys.modules, "f1verse.sources.wikidata", stub)


def test_upstream_fills_a_circuit_the_table_never_recorded(monkeypatch):
    # Kyalami last held a Grand Prix in 1993, so no recent season sweep
    # will ever curate it — the upstream is all there is
    stub = _Wikidata(length_m=4522, opened="1961")
    _patch(monkeypatch, stub)
    entry = reference.facts("Kyalami", "https://en.wikipedia.org/wiki/Kyalami")
    assert entry["length_m"] == 4522
    assert entry["provenance"]["length_m"] == "wikidata"


def test_a_circuit_is_found_under_the_name_another_feed_uses():
    # one circuit, two upstream names
    assert reference.facts("Lusail")["length_m"] == 5419
    assert reference.facts("Losail")["length_m"] == 5419
    assert reference.facts("Marina Bay")["corners"] == 19


def test_a_curated_value_outranks_the_upstream_field_by_field(monkeypatch):
    # the upstream carries a stale length and an opening date we lack
    _patch(monkeypatch, _Wikidata(length_m=4307, opened="1948"))
    entry = reference.facts("Zandvoort", "https://en.wikipedia.org/wiki/x")
    assert entry["length_m"] == 4259                     # checked by a human
    assert entry["provenance"]["length_m"] == "curated"
    assert entry["opened"] == "1948"                     # gap filled upstream
    assert entry["provenance"]["opened"] == "wikidata"


def test_an_unusable_upstream_answer_is_not_treated_as_a_fact(monkeypatch):
    _patch(monkeypatch, _Wikidata(available=False, length_m=None))
    assert reference.facts("Nowhere", "https://en.wikipedia.org/wiki/x") is None


def test_a_broken_upstream_never_breaks_a_lookup(monkeypatch):
    class _Boom:
        def circuit_facts(self, url):
            raise RuntimeError("network down")

    _patch(monkeypatch, _Boom())
    # the curated layer still answers
    assert reference.facts("Zandvoort", "https://x/wiki/y")["length_m"] == 4259


def test_a_disputed_field_is_left_out_rather_than_picked():
    # secondary reports give Madrid either 20 or 22 corners and the official
    # page states none, so no count is asserted — while the length, which
    # the official page does give, is
    madrid = reference.facts("Madring")
    assert madrid["length_m"] == 5416 and "corners" not in madrid
    assert madrid["race_laps"] == 57
    assert "disagree" in madrid["notes"]


def test_an_omitted_field_audits_as_unchecked_not_agreed():
    result = reference.audit("Madring", {"lap_distance_m": 5416.0,
                                         "corners": 22})
    states = {c["field"]: c["state"] for c in result["checks"]}
    assert states["length_m"] == "agrees"
    # no published corner count exists to compare against, and a missing
    # comparison must never read as a passing one
    assert states["corners"] == "unchecked"


def test_the_official_figure_wins_over_circulated_secondary_ones():
    # 4928 and 4940 both circulate for Singapore; the official page says 4927
    singapore = reference.facts("Marina Bay")
    assert singapore["length_m"] == 4927
    assert singapore["race_laps"] == 62


def test_entries_go_stale_on_a_season_boundary():
    fresh = reference.stale(today="2026-09-02")
    assert fresh == []
    # two seasons on, everything the sweep recorded wants another look
    later = reference.stale(today="2028-03-01")
    assert {row["circuit"] for row in later} >= {"Zandvoort", "Monza"}
    assert later[0]["reason"] == "not checked since last season"
    assert later[0]["age_days"] > reference.REVIEW_AFTER_DAYS


def test_review_separates_new_from_moved_from_untouched():
    verdict = reference.review({
        "Zandvoort": {"length_m": 4259, "race_laps": 72},     # unchanged
        "Monza": {"length_m": 5800},                          # reprofiled
        "Bogota": {"length_m": 4800},                         # a new venue
    }, today="2026-09-02")
    assert "Zandvoort" in verdict["unchanged"]
    assert verdict["changed"] == [{"circuit": "Monza", "changes": [
        {"field": "length_m", "stored": 5793, "official": 5800}]}]
    assert verdict["added"][0]["circuit"] == "Bogota"
    # circuits the season no longer visits are named, never dropped
    assert "Imola" in verdict["not_in_sweep"]


def test_a_sweep_never_clears_what_only_a_human_knows():
    # corner counts and notes are not published by the sweep, so they must
    # not be among the fields it is allowed to overwrite
    assert "corners" not in reference.SWEPT
    assert "notes" not in reference.SWEPT
    assert "length_m" in reference.SWEPT


def test_an_audit_reports_the_age_of_what_it_agreed_with():
    result = reference.audit("Zandvoort", {"lap_distance_m": 4274.4,
                                           "corners": 14})
    assert result["verdict"] == "agrees"
    assert result["checked_age_days"] >= 0


def test_the_documented_public_names_exist():
    # README and AGENTS.md promise these; a tool entry is not an API
    import f1verse
    for name in ("circuit_survey", "circuit_facts", "circuit_audit",
                 "circuit_review", "circuit_facts_stale"):
        assert hasattr(f1verse, name), name
        assert name in f1verse.__all__, name
