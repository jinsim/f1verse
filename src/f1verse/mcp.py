"""MCP server — F1 as a tool an AI agent can hold.

Run it with no install step and no dependencies::

    uvx --from f1verse f1verse-mcp

and point a client at it::

    {"mcpServers": {"f1verse": {"command": "uvx", "args": ["--from", "f1verse", "f1verse-mcp"]}}}

The transport is newline-delimited JSON-RPC 2.0 over stdio, implemented
here in the standard library — the same zero-dependency rule as the rest
of f1verse, which is why the process starts in milliseconds rather than
after a scientific stack is unpacked into a throwaway environment.

Tools come from :mod:`f1verse._tools`, so the catalogue an agent sees and
the catalogue a Python caller sees can never drift apart.
"""
from __future__ import annotations

import json
import sys

from ._tools import call as _call, catalog as _catalog
from ._version import __version__

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "f1verse", "title": "f1verse — Formula 1 story layer",
               "version": __version__}
INSTRUCTIONS = (
    "Formula 1 data with the domain rules already applied. Resolve vague "
    "references first: f1_season_status turns 'the last race' into a round "
    "number. For a whole race prefer f1_race_story over several narrow calls. "
    "Results are provisional until the stewards finish — within a few hours "
    "of a session, check f1_data_quality before calling anything final. "
    "Seasons 2023 onward for race data; careers and records reach back to 1950."
)

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603


def _result(request_id, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def _content(obj) -> list:
    return [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}]


def handle(message: dict) -> dict | None:
    """Answer one JSON-RPC message. Returns ``None`` for notifications."""
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method is None:
        return _error(request_id, INVALID_REQUEST, "missing 'method'")
    if request_id is None:                      # notification — never answered
        return None

    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(request_id, {
            "protocolVersion": asked if isinstance(asked, str) else PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        })

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": _catalog("mcp")})

    if method == "tools/call":
        name = params.get("name")
        try:
            payload = _call(name, params.get("arguments") or {})
        except Exception as exc:                # reported to the model, not fatal
            text = f"{type(exc).__name__}: {exc}"
            return _result(request_id,
                           {"content": [{"type": "text", "text": text}],
                            "isError": True})
        return _result(request_id, {"content": _content(payload),
                                    "structuredContent": {"result": payload},
                                    "isError": False})

    return _error(request_id, METHOD_NOT_FOUND, f"unknown method {method!r}")


def serve(stdin=None, stdout=None) -> None:
    """Read messages until stdin closes, writing one JSON reply per line."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply = _error(None, PARSE_ERROR, "invalid JSON")
        else:
            try:
                reply = handle(message)
            except Exception as exc:            # never take the server down
                reply = _error(message.get("id"), INTERNAL_ERROR,
                               f"{type(exc).__name__}: {exc}")
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> int:
    import os
    override = os.environ.get("F1VERSE_CACHE")
    if override:
        from . import http
        http.enable_cache(override)
    try:
        serve()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
