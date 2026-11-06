# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""The agent-facing surface: tool schemas and the dispatcher.

These are the contract an LLM sees. They must hold without a network —
a model asking "what can this do?" should never pay for a fetch.
"""
import json

import pytest

import f1verse
from f1verse import _tools


def test_catalog_is_json_serialisable_and_complete():
    cat = f1verse.tools()
    assert json.dumps(cat)
    assert [t["name"] for t in cat] == list(_tools.NAMES)
    for tool in cat:
        assert tool["description"].strip()
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        for name in schema["required"]:
            assert name in schema["properties"]
        for name, prop in schema["properties"].items():
            assert prop.get("description"), f"{tool['name']}.{name} undocumented"


def test_every_catalogued_tool_has_a_handler():
    assert set(_tools.NAMES) == set(_tools._HANDLERS)


def test_openai_dialect_wraps_the_same_schemas():
    mcp = {t["name"]: t["inputSchema"] for t in f1verse.tools()}
    for tool in f1verse.tools("openai"):
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["parameters"] == mcp[fn["name"]]


def test_unknown_dialect_names_the_valid_ones():
    with pytest.raises(ValueError, match="mcp"):
        f1verse.tools("anthropic")


def test_unknown_tool_error_lists_the_real_ones():
    """A model that guesses wrong must be able to recover from the message."""
    with pytest.raises(LookupError) as err:
        f1verse.call_tool("f1_race_summary", {})
    assert "f1_race_story" in str(err.value)


def test_missing_argument_error_names_it():
    with pytest.raises(TypeError, match="year"):
        f1verse.call_tool("f1_standings", {})


def test_unexpected_argument_error_names_what_is_accepted():
    with pytest.raises(TypeError, match="driver_id"):
        f1verse.call_tool("f1_driver_career",
                          {"driver_id": "hamilton", "season": 2026})


def test_tyre_tool_passes_the_explicit_scenario_to_both_analyses(monkeypatch):
    from f1verse import race, strategy
    token = object()
    calls = []
    monkeypatch.setattr(race, "load", lambda *args: token)
    def analysis(loaded, *, fuel_model):
        assert loaded is token
        calls.append(fuel_model)
        return []
    monkeypatch.setattr(strategy, "stint_degradation", analysis)
    monkeypatch.setattr(strategy, "circuit_abrasion", analysis)
    scenario = {"start_kg": 70, "burn_kg_per_lap": 1.1, "cost_s_per_kg": 0.025}
    f1verse.call_tool("f1_tyre_wear", {"year": 2026, "round": 12, "fuel_model": scenario})
    assert calls == [scenario, scenario]
    calls.clear()
    f1verse.call_tool("f1_tyre_wear", {"year": 2026, "round": 12})
    assert calls == [None, None]


@pytest.mark.parametrize("scenario, message", [
    ([], "object"), ({}, "start_kg"),
    ({"start_kg": 70, "burn_kg_per_lap": True, "cost_s_per_kg": 0.025}, "number"),
    ({"start_kg": 70, "burn_kg_per_lap": float("nan"), "cost_s_per_kg": 0.025}, "finite"),
    ({"start_kg": 70, "burn_kg_per_lap": float("inf"), "cost_s_per_kg": 0.025}, "finite"),
    ({"start_kg": -1, "burn_kg_per_lap": 1, "cost_s_per_kg": 0.025}, "range"),
    ({"start_kg": 70, "burn_kg_per_lap": 1, "cost_s_per_kg": 0.025, "extra": 1}, "unexpected"),
])
def test_tyre_scenario_is_validated_before_fetching(scenario, message, monkeypatch):
    from f1verse import race
    def no_fetch(*args):
        raise AssertionError("invalid scenario must not fetch data")
    monkeypatch.setattr(race, "load", no_fetch)
    with pytest.raises((TypeError, ValueError), match=message):
        f1verse.call_tool("f1_tyre_wear", {"year": 2026, "round": 12, "fuel_model": scenario})
