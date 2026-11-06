# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""The bundled MCP server — JSON-RPC framing, offline.

The transport is hand-rolled standard library, so the protocol details it
gets right are only guaranteed by these tests.
"""
import io
import json
import re
import subprocess
import sys

import pytest

from f1verse import mcp


def rpc(method, params=None, request_id=1):
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    return mcp.handle(msg)


def test_initialize_negotiates_only_a_supported_protocol_version():
    """Unknown client versions must not be advertised as supported."""
    out = rpc("initialize", {"protocolVersion": "2999-01-01"})["result"]
    assert out["protocolVersion"] == mcp.PROTOCOL_VERSION
    assert out["capabilities"]["tools"] == {"listChanged": False}
    assert out["serverInfo"]["name"] == "f1verse"
    assert "provisional" in out["instructions"]


def test_malformed_messages_do_not_kill_the_server():
    stdin = io.StringIO('[]\nnull\n{"id": 1, "method": "ping", "params": [1]}\n'
                        '{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
    stdout = io.StringIO()
    mcp.serve(stdin, stdout)
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert len(replies) == 4
    assert all(r["error"]["code"] == mcp.INVALID_REQUEST for r in replies[:3])
    assert replies[-1]["result"] == {}


def test_initialize_falls_back_when_no_version_offered():
    out = rpc("initialize", {})["result"]
    assert out["protocolVersion"] == mcp.PROTOCOL_VERSION


def test_tools_list_matches_the_library_catalogue():
    import f1verse
    listed = rpc("tools/list")["result"]["tools"]
    assert listed == f1verse.tools()


def test_notifications_are_not_answered():
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_is_a_protocol_error():
    err = rpc("unknown/method")["error"]
    assert err["code"] == mcp.METHOD_NOT_FOUND


def test_tool_failure_is_reported_to_the_model_not_the_transport():
    """A bad argument is the model's problem to fix, not a broken server."""
    out = rpc("tools/call", {"name": "f1_standings", "arguments": {}})["result"]
    assert out["isError"] is True
    assert "year" in out["content"][0]["text"]


def test_serve_reads_lines_and_survives_bad_json():
    stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
                        'not json\n'
                        '\n'
                        '{"jsonrpc":"2.0","id":2,"method":"ping"}\n')
    stdout = io.StringIO()
    mcp.serve(stdin, stdout)
    replies = [json.loads(l) for l in stdout.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2]
    assert replies[1]["error"]["code"] == mcp.PARSE_ERROR


@pytest.mark.parametrize("change", [
    {"jsonrpc": "1.0"}, {"method": []}, {"method": ""},
    {"params": []}, {"params": None}, {"params": False},
    {"id": True}, {"id": 1.5}, {"id": None}, {"id": {}},
])
def test_invalid_envelopes_are_recoverable(change):
    message = {"jsonrpc": "2.0", "method": "ping", "id": 1}
    message.update(change)
    assert mcp.handle(message)["error"]["code"] == mcp.INVALID_REQUEST
    assert rpc("ping", request_id=0)["result"] == {}


def test_resources_are_offline_and_share_the_tool_catalogue(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("discovery must not fetch upstream data")
    import urllib.request
    import f1verse
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    capabilities = rpc("initialize")["result"]["capabilities"]
    assert "resources" in capabilities and "prompts" in capabilities
    resources = rpc("resources/list")["result"]["resources"]
    for resource in resources:
        content, = rpc("resources/read", {"uri": resource["uri"]})["result"]["contents"]
        assert content["mimeType"] == resource["mimeType"]
        if content["mimeType"] == "application/json":
            assert json.loads(content["text"]) == f1verse.tools()
        else:
            assert "Skipped checks" in content["text"]
    assert rpc("resources/read", {"uri": "file:///secret"})["error"]["code"] == mcp.INVALID_PARAMS


def test_prompt_workflows_only_reference_available_tools(monkeypatch):
    def no_call(*args, **kwargs):
        raise AssertionError("prompt retrieval must not execute tools")
    import f1verse
    monkeypatch.setattr(mcp, "_call", no_call)
    names = {tool["name"] for tool in f1verse.tools()}
    for prompt in rpc("prompts/list")["result"]["prompts"]:
        out = rpc("prompts/get", {"name": prompt["name"],
                  "arguments": {"year": "2026", "round": "12"}})["result"]
        message, = out["messages"]
        assert message["role"] == "user"
        text = message["content"]["text"]
        assert "2026" in text and "12" in text
        assert set(re.findall(r"\bf1_\w+", text)) <= names


@pytest.mark.parametrize("params", [
    {"name": "missing"}, {"name": []}, {"name": "race-brief"},
    {"name": "race-brief", "arguments": []},
    {"name": "race-brief", "arguments": {"year": 2026, "round": "12"}},
    {"name": "race-brief", "arguments": {"year": "2022", "round": "1"}},
    {"name": "race-brief", "arguments": {"year": "2026", "round": "0"}},
    {"name": "race-brief", "arguments": {"year": "2026; run", "round": "1"}},
])
def test_invalid_prompt_arguments_report_protocol_errors(params):
    assert rpc("prompts/get", params)["error"]["code"] == mcp.INVALID_PARAMS


def test_real_stdio_process_handles_discovery_and_rejects_non_json_numbers():
    requests = [
        '{"jsonrpc":"2.0","id":1,"method":"initialize"}',
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","id":NaN,"method":"ping"}',
        '{"jsonrpc":"2.0","id":2,"method":"resources/list"}',
        '{"jsonrpc":"2.0","id":3,"method":"prompts/list"}',
        '{"jsonrpc":"2.0","id":4,"method":"tools/list"}',
    ]
    proc = subprocess.run([sys.executable, "-m", "f1verse.mcp"],
                          input="\n".join(requests) + "\n", text=True,
                          capture_output=True, timeout=10, check=True)
    replies = [json.loads(line) for line in proc.stdout.splitlines()]
    assert [reply["id"] for reply in replies] == [1, None, 2, 3, 4]
    assert replies[1]["error"]["code"] == mcp.PARSE_ERROR
    assert replies[-1]["result"]["tools"]
    assert not proc.stderr
