# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

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
               "version": __version__,
               "websiteUrl": "https://github.com/jinsim/f1verse"}
INSTRUCTIONS = (
    "Formula 1 data with the domain rules already applied. Resolve vague "
    "references first: f1_season_status turns 'the last race' into a round "
    "number. For a whole race prefer f1_race_story over several narrow calls. "
    "Results are provisional until the stewards finish — within a few hours "
    "of a session, check f1_data_quality before calling anything final. "
    "A skipped check is unavailable evidence, not agreement. Read "
    "f1verse://guide for analysis workflows and coverage. Prompts are starting "
    "instructions, not fetched results. Live-feed race tools cover 2023 onward; "
    "careers and records reach back to 1950."
)

_GUIDE = """# f1verse analysis guide

Discover current tools with tools/list; f1verse://tools returns the same catalogue.
Resolve relative dates using the current year and f1_season_status. Confirm the
event and session before fetching; live-feed race tools cover 2023 onward. For
older races use f1_archive_race (1996-2022), with its coverage block.

For a race explanation start with f1_race_story, then f1_data_quality. Use narrow
event, pace or strategy tools only for unanswered questions. Check publishable,
lifecycle, missing fields, source age, revisions and crosscheck evidence before
stating a result as final. Skipped checks do not establish agreement. If access
fails, f1_source_status reports configured access and rate budgets without
revealing credentials. It cannot obtain or renew subscriptions.

Separate observed events, retrospective heuristics and model scenarios. Turning
points rank candidates, not causal effects; pace changes do not identify causes.
Retirement survival is descriptive and race-level dependence limits inference.
State sample sizes, assumptions, exclusions and uncertainty for estimates.
Keep mathematical title eligibility distinct from title win probabilities.
For 2026 onward, do not infer DRS from an empty channel or describe fuel-corrected
tyre wear without an explicit fuel scenario. Missing coverage is not zero.

The repository's agent skill supplies reusable analysis instructions. The MCP
server supplies callable tools, resources and prompts. Installing a skill does
not connect this server or grant upstream data access. Runtime responses are
evidence; instructions and prompt templates contain no race observations.
"""

_PROMPTS = (
    {"name": "race-brief", "title": "Evidence-backed race brief",
     "description": "Explain a race with lifecycle, source checks and labelled uncertainty.",
     "arguments": [{"name": "year", "description": "Season, 2023 onward", "required": True},
                   {"name": "round", "description": "Positive championship round", "required": True}]},
    {"name": "strategy-review", "title": "Race strategy review",
     "description": "Review pit exchanges and pace with assumptions and causal limits.",
     "arguments": [{"name": "year", "description": "Season, 2023 onward", "required": True},
                   {"name": "round", "description": "Positive championship round", "required": True}]},
)

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _result(request_id, payload: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": payload}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def _content(obj) -> list:
    return [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}]


def _prompt(params: dict) -> dict:
    name = params.get("name")
    if not isinstance(name, str) or name not in {p["name"] for p in _PROMPTS}:
        raise ValueError("unknown prompt; available: race-brief, strategy-review")
    args = params.get("arguments", {})
    if not isinstance(args, dict) or set(args) != {"year", "round"}:
        raise ValueError("prompt arguments must contain year and round")
    for key in ("year", "round"):
        value = args[key]
        if not isinstance(value, str) or not value.isascii() or not value.isdigit():
            raise ValueError(f"{key} must be a decimal integer string")
    year, rnd = int(args["year"]), int(args["round"])
    if year < 2023 or rnd < 1:
        raise ValueError("race prompts require year >= 2023 and round >= 1")
    text = (f"Analyse season {year}, round {rnd}. Start with f1_race_story and "
            "f1_data_quality for this event. Report lifecycle, coverage, missing "
            "or skipped checks and source corrections. Cite returned evidence; "
            "do not invent unavailable results. ")
    if name == "race-brief":
        text += ("Write a concise race brief. Use f1_race_events or "
                 "f1_turning_points only when useful; distinguish observations "
                 "from heuristic rankings and title forecasts.")
    else:
        text += ("Use the story's strategy evidence, f1_tyre_wear and "
                 "f1_pace_changes to review pit exchanges "
                 "and clean-stint pace. State sample sizes and assumptions. "
                 "Observed position gains do not prove a pit stop caused them. "
                 "For 2026 onward, corrected wear requires an explicit fuel "
                 "scenario; otherwise report raw trends and their limits.")
    return {"description": next(p["description"] for p in _PROMPTS if p["name"] == name),
            "messages": [{"role": "user", "content": {"type": "text", "text": text}}]}


def handle(message: dict) -> dict | None:
    """Answer one JSON-RPC message. Returns ``None`` for notifications."""
    if not isinstance(message, dict):
        return _error(None, INVALID_REQUEST, "request must be a JSON object")
    method = message.get("method")
    request_id = message.get("id")
    if "id" in message and (isinstance(request_id, bool)
                            or not isinstance(request_id, (str, int))):
        return _error(None, INVALID_REQUEST, "id must be a string or integer")
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str) or not method:
        return _error(request_id, INVALID_REQUEST, "expected jsonrpc '2.0' and a nonempty method")
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _error(request_id, INVALID_REQUEST, "params must be an object")

    if "id" not in message:                    # notification — never answered
        return None

    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False},
                             "resources": {"listChanged": False},
                             "prompts": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        })

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": _catalog("mcp")})

    if method == "resources/list":
        return _result(request_id, {"resources": [
            {"uri": "f1verse://guide", "name": "Analysis guide", "mimeType": "text/markdown"},
            {"uri": "f1verse://tools", "name": "Current tool catalogue", "mimeType": "application/json"},
        ]})

    if method == "resources/read":
        uri = params.get("uri")
        if uri == "f1verse://guide":
            mime, text = "text/markdown", _GUIDE
        elif uri == "f1verse://tools":
            mime, text = "application/json", json.dumps(_catalog("mcp"), ensure_ascii=False)
        else:
            return _error(request_id, INVALID_PARAMS,
                          "unknown resource; available: f1verse://guide, f1verse://tools")
        return _result(request_id, {"contents": [{"uri": uri, "mimeType": mime, "text": text}]})

    if method == "prompts/list":
        return _result(request_id, {"prompts": list(_PROMPTS)})

    if method == "prompts/get":
        try:
            return _result(request_id, _prompt(params))
        except (ValueError, TypeError) as exc:
            return _error(request_id, INVALID_PARAMS, str(exc))

    if method == "tools/call":
        name = params.get("name")
        try:
            payload = _call(name, params.get("arguments"))
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
            message = json.loads(line, parse_constant=_reject_constant)
        except ValueError:
            reply = _error(None, PARSE_ERROR, "invalid JSON")
        else:
            try:
                reply = handle(message)
            except Exception as exc:            # never take the server down
                reply = _error(message.get("id") if isinstance(message, dict) else None, INTERNAL_ERROR,
                               f"{type(exc).__name__}: {exc}")
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()


def _reject_constant(value):
    raise ValueError(f"non-JSON numeric constant: {value}")


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
