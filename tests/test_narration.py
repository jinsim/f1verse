# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Grounded generation: facts in Python, wording from a model, always verified."""
import json

import pytest

import f1verse
from f1verse import narration as N

FACTS = {
    "event": {"name": "Dutch Grand Prix", "laps": 72},
    "podium": [{"position": 1, "driver": "NOR", "name": "Lando NORRIS",
                "team": "McLaren", "gap": "WINNER"},
               {"position": 2, "driver": "ANT", "name": "Kimi ANTONELLI",
                "team": "Mercedes", "gap": "+11.536s"}],
    "laps_led": [{"driver": "ANT", "laps": 32}, {"driver": "NOR", "laps": 31}],
    "most_laps_led": {"driver": "ANT", "laps": 32},
    "lead_changes": 6,
    "retirements": [{"driver": "VER"}],
    "fastest_pace": [],
    "interruptions": {"red_flag_laps": [2], "sc_vsc_periods": []},
}


def test_quoted_numbers_pass():
    text = "NORRIS won the Dutch Grand Prix over 72 laps; ANT led 32."
    assert N.verify(text, FACTS)["ok"]


@pytest.mark.parametrize("text,expected", [
    ("NOR won by 4.5 seconds.", ["4.5"]),
    ("ANT led 45 laps.", ["45"]),
    ("A 1:22.100 lap sealed it.", ["1:22.100"]),
])
def test_invented_numbers_are_caught(text, expected):
    report = N.verify(text, FACTS)
    assert not report["ok"]
    assert report["unsupported_numbers"] == expected


def test_rounding_counts_as_invention():
    """+11.536s must not become '11.5' — precision is the point."""
    assert N.unsupported_numbers("ANT finished 11.5s behind.", FACTS) == ["11.5"]


def test_unknown_driver_codes_are_caught():
    report = N.verify("HAM took third.", FACTS)
    assert not report["ok"]
    assert "HAM" in report["unknown_names"]


def test_prompt_is_stable_and_structured():
    """Identical facts must produce an identical prompt, or neither
    provider-side prefix caching nor local caching can work."""
    a, b = N.prompt(FACTS), N.prompt(dict(reversed(list(FACTS.items()))))
    assert a == b
    assert "Do no arithmetic" in a
    json.loads(a.split("Facts:\n", 1)[1])      # facts travel as valid JSON


def test_narrate_falls_back_to_template_when_generation_lies():
    """A wrong sentence must never reach the caller; a plain one may."""
    race_facts_only = {"calls": 0}

    class FakeRace:
        def results(self):
            return [{"position": 1, "abbr": "NOR", "name": "Lando NORRIS",
                     "team": "McLaren", "gap": "WINNER"}]
        def laps_led(self): return {"NOR": 72}
        def leader_runs(self): return [{"abbr": "NOR", "from": 1, "to": 72}]
        def race_pace(self): return {}
        def interruptions(self): return {"red_flag_laps": [], "sc_vsc_bands": []}
        def story(self):
            return {"event": {"name": "Test GP", "location": "Nowhere",
                              "round": 1, "total_laps": 72}}

    def liar(_prompt):
        race_facts_only["calls"] += 1
        return "NORRIS won by 9.999 seconds."

    out = N.narrate(FakeRace(), liar, attempts=2)
    assert out["source"] == "template"
    assert "9.999" not in out["text"]
    assert race_facts_only["calls"] == 2          # retried before falling back


def test_brief_needs_no_model(race):
    text = f1verse.brief(race)
    assert "Dutch Grand Prix" in text
    assert N.verify(text, f1verse.race_facts(race))["ok"]


def test_retired_drivers_are_legitimate_subjects(race):
    """Every driver in the fact sheet may be named, not just the podium."""
    facts = f1verse.race_facts(race)
    retired = facts["retirements"][0]["driver"]
    assert N.verify(f"{retired} retired.", facts)["ok"]


def test_only_verified_generation_is_cached(tmp_path):
    class FakeRace:
        def results(self):
            return [{"position": 1, "abbr": "NOR", "name": "Lando NORRIS",
                     "team": "McLaren", "gap": "WINNER"}]
        def laps_led(self): return {"NOR": 72}
        def leader_runs(self): return [{"abbr": "NOR", "from": 1, "to": 72}]
        def race_pace(self): return {}
        def interruptions(self): return {"red_flag_laps": [], "sc_vsc_bands": []}
        def story(self):
            return {"event": {"name": "Test GP", "location": "Nowhere",
                              "round": 1, "total_laps": 72}}

    calls = {"count": 0}
    def generator(_prompt):
        calls["count"] += 1
        return "Lando NORRIS won over 72 laps."

    first = N.narrate(FakeRace(), generator, cache_dir=tmp_path)
    second = N.narrate(FakeRace(), generator, cache_dir=tmp_path)
    assert first["source"] == "generated"
    assert second["source"] == "cache"
    assert calls["count"] == 1
