"""Agent-facing tool catalogue — the library describes itself.

An LLM pipeline should not need a hand-written adapter to call f1verse.
:func:`catalog` emits ready-to-use tool definitions and :func:`call`
executes one by name, so wiring f1verse into an agent is three lines:

>>> import f1verse
>>> f1verse.tools()                       # JSON schemas, MCP dialect
>>> f1verse.call_tool("f1_race_story", {"year": 2026, "round": 12})

Both are plain stdlib and JSON-safe, like everything else here. The same
catalogue backs the bundled MCP server (``f1verse-mcp``).
"""
from __future__ import annotations

from ._json import jsonsafe

_YEAR = {"type": "integer", "description": "Season year, e.g. 2026. Race data 2023+."}
_ROUND = {"type": "integer", "description": "Round number within the season, 1-based."}
_SESSION = {"type": "string",
            "description": "Session name as the calendar spells it: Race, "
                           "Qualifying, Sprint, Sprint Qualifying, Practice 1-3. "
                           "Defaults to Race.",
            "default": "Race"}

_SPECS = [
    {
        "name": "f1_race_story",
        "summary": "Everything that happened in one race, as structured JSON.",
        "description": (
            "The whole race in one call: final results with broadcast-convention "
            "gaps, lead changes, laps led per driver, the event timeline, tyre "
            "stints, median race pace (pit/SC/VSC laps excluded), and safety-car "
            "interruptions. Use this first for any 'what happened in race X' "
            "question — it is one request instead of six."),
        "params": {"year": _YEAR, "round": _ROUND},
        "required": ["year", "round"],
    },
    {
        "name": "f1_race_brief",
        "summary": "A short factual race summary in plain English.",
        "description": (
            "A publishable prose summary of a race, built from templates only — "
            "every number in it comes from the data, so it is safe to quote "
            "verbatim. Use when the user wants a readable recap rather than "
            "fields to compute with."),
        "params": {"year": _YEAR, "round": _ROUND},
        "required": ["year", "round"],
    },
    {
        "name": "f1_session_results",
        "summary": "Classification for any session of a weekend.",
        "description": (
            "Results for one session, classified the way that kind of session "
            "actually is: races give position and gap (lapped cars as '+1 LAP'), "
            "qualifying gives per-segment times with gaps to that segment's "
            "fastest and where each driver was eliminated, practice gives a "
            "best-lap table."),
        "params": {"year": _YEAR, "round": _ROUND, "session": _SESSION},
        "required": ["year", "round"],
    },
    {
        "name": "f1_weekend_sessions",
        "summary": "Which sessions a given round has, in order.",
        "description": (
            "Lists the sessions of a race weekend with start and end times — the "
            "valid inputs for the 'session' argument of the other tools. Call "
            "this when unsure whether a round was a sprint weekend."),
        "params": {"year": _YEAR, "round": _ROUND},
        "required": ["year", "round"],
    },
    {
        "name": "f1_season_status",
        "summary": "Where the season stands right now and what is next.",
        "description": (
            "The latest completed race, sessions that have finished and settled, "
            "the next session and how many hours until it starts. Use this to "
            "answer 'when is the next race' or to resolve 'the last race' into a "
            "concrete round number before calling the other tools."),
        "params": {"year": _YEAR},
        "required": ["year"],
    },
    {
        "name": "f1_standings",
        "summary": "Championship standings after the latest completed round.",
        "description": (
            "Drivers' or constructors' championship table, with points and wins, "
            "as of the most recent round that has been scored."),
        "params": {"year": _YEAR,
                   "kind": {"type": "string", "enum": ["driver", "constructor"],
                            "default": "driver",
                            "description": "Which championship table to return."}},
        "required": ["year"],
    },
    {
        "name": "f1_driver_career",
        "summary": "A driver's career totals, 1950 to today.",
        "description": (
            "Starts, wins, podiums, poles and points for one driver across all "
            "of F1 history, plus the next round-number milestones they are "
            "approaching. Takes an Ergast-style driver id such as "
            "'max_verstappen', 'hamilton' or 'leclerc'."),
        "params": {"driver_id": {"type": "string",
                                 "description": "Ergast/Jolpica driver id, e.g. "
                                                "'max_verstappen', 'hamilton'."}},
        "required": ["driver_id"],
    },
    {
        "name": "f1_data_quality",
        "summary": "Is this session's data complete, current and safe to publish?",
        "description": (
            "Completeness per field, how old the fetched copy is, whether the "
            "classification is still provisional (stewards rewrite results hours "
            "after the flag), corrections observed so far, agreement between "
            "independent sources, and a single 'publishable' verdict. Call this "
            "before stating a result as final, especially within a few hours of "
            "a session ending."),
        "params": {"year": _YEAR, "round": _ROUND, "session": _SESSION},
        "required": ["year", "round"],
    },
]


def _story(year, round, **_):
    from .race import load
    return load(year, round).story()


def _brief(year, round, **_):
    from .narration import brief
    from .race import load
    race = load(year, round)
    return {"event": race.meeting.get("meeting_name"), "text": brief(race),
            "state": race.lifecycle}


def _results(year, round, session="Race", **_):
    from .race import load_session
    s = load_session(year, round, session)
    return {"session": s.name, "state": s.lifecycle, "results": s.results()}


def _sessions(year, round, **_):
    from .race import sessions
    return {"sessions": sessions(year, round)}


def _status(year, **_):
    from .schedule import status
    return status(year)


def _standings(year, kind="driver", **_):
    from .history import standings
    return standings(year, kind)


def _career(driver_id, **_):
    from .history import career, milestones
    return {"career": career(driver_id), "milestones": milestones(driver_id)}


def _quality(year, round, session="Race", **_):
    from .race import load_session
    return load_session(year, round, session).quality_report()


_HANDLERS = {
    "f1_race_story": _story,
    "f1_race_brief": _brief,
    "f1_session_results": _results,
    "f1_weekend_sessions": _sessions,
    "f1_season_status": _status,
    "f1_standings": _standings,
    "f1_driver_career": _career,
    "f1_data_quality": _quality,
}

NAMES = tuple(spec["name"] for spec in _SPECS)


def _schema(spec: dict) -> dict:
    return {"type": "object", "properties": dict(spec["params"]),
            "required": list(spec["required"]), "additionalProperties": False}


def catalog(dialect: str = "mcp") -> list:
    """Tool definitions for every public capability, ready to hand to a model.

    *dialect* is ``"mcp"`` (default, ``{name, description, inputSchema}``) or
    ``"openai"`` (``{type: "function", function: {...}}``), which is also the
    shape Anthropic's Messages API and most agent frameworks accept after a
    trivial rename. Unknown dialects raise ``ValueError``.
    """
    if dialect not in ("mcp", "openai"):
        raise ValueError(
            f"unknown tool dialect {dialect!r} — use 'mcp' or 'openai'")
    out = []
    for spec in _SPECS:
        text = f"{spec['summary']} {spec['description']}"
        if dialect == "mcp":
            out.append({"name": spec["name"], "title": spec["summary"],
                        "description": text, "inputSchema": _schema(spec)})
        else:
            out.append({"type": "function",
                        "function": {"name": spec["name"], "description": text,
                                     "parameters": _schema(spec)}})
    return jsonsafe(out)


def call(name: str, arguments: dict | None = None):
    """Run one catalogued tool by name and return its JSON-safe result.

    Unknown names raise ``LookupError`` naming the tools that do exist, and
    missing arguments raise ``TypeError`` naming the ones required — both so
    that a model reading the error can correct itself without the docs.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        raise LookupError(f"unknown tool {name!r} — available: "
                          f"{', '.join(NAMES)}")
    args = dict(arguments or {})
    spec = next(s for s in _SPECS if s["name"] == name)
    missing = [k for k in spec["required"] if k not in args]
    if missing:
        raise TypeError(f"{name} needs {', '.join(missing)} — required "
                        f"arguments are {', '.join(spec['required'])}")
    extra = [k for k in args if k not in spec["params"]]
    if extra:
        raise TypeError(f"{name} got unexpected argument(s) "
                        f"{', '.join(extra)} — it accepts "
                        f"{', '.join(spec['params'])}")
    return jsonsafe(handler(**args))
