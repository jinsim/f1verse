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
