# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""The bundled MCP server — JSON-RPC framing, offline.

The transport is hand-rolled standard library, so the protocol details it
gets right are only guaranteed by these tests.
"""
import io
import json

from f1verse import mcp


def rpc(method, params=None, request_id=1):
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        msg["params"] = params
    return mcp.handle(msg)


def test_initialize_echoes_the_client_protocol_version():
    """Clients negotiate; a server that answers with its own build breaks."""
    out = rpc("initialize", {"protocolVersion": "2999-01-01"})["result"]
    assert out["protocolVersion"] == "2999-01-01"
    assert out["capabilities"]["tools"] == {"listChanged": False}
    assert out["serverInfo"]["name"] == "f1verse"
    assert "provisional" in out["instructions"]


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
    err = rpc("resources/list")["error"]
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
