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
    {
        "name": "f1_tyre_wear",
        "summary": "How fast each set of tyres degraded, stint by stint.",
        "description": (
            "Per-stint degradation in seconds per lap, computed on "
            "fuel-normalised clean laps only (pit, safety-car and traffic laps "
            "excluded), plus a circuit abrasion verdict relative to an ordinary "
            "surface. Every rate reports how many clean laps it stands on; "
            "stints too short to judge say so instead of guessing."),
        "params": {"year": _YEAR, "round": _ROUND},
        "required": ["year", "round"],
    },
    {
        "name": "f1_deleted_laps",
        "summary": "Lap times the stewards struck out, with reinstatements.",
        "description": (
            "Every lap-time deletion race control announced in a session, with "
            "the car, the time, the stated reason, and whether the deletion "
            "still stands — a reinstated lap is reported with the reversal "
            "visible rather than silently dropped. Use before treating a "
            "fastest lap or a qualifying position as settled."),
        "params": {"year": _YEAR, "round": _ROUND, "session": _SESSION},
        "required": ["year", "round"],
    },
    {
        "name": "f1_running_order",
        "summary": "Who was where at the end of every lap.",
        "description": (
            "The order on track lap by lap, plus how much each lap churned "
            "and who made the biggest single gain. This is the data behind "
            "any position-change chart; use it for 'how did the race "
            "unfold' rather than fetching results and guessing."),
        "params": {"year": _YEAR, "round": _ROUND},
        "required": ["year", "round"],
    },
    {
        "name": "f1_battles",
        "summary": "Pairs that ran nose-to-tail, and for how long.",
        "description": (
            "Every stretch where two cars held consecutive positions within "
            "1.5 seconds for at least three laps, with the closest the gap "
            "got. Finds the fights a results table hides — a scrap for "
            "eighth that ran twenty laps never shows up in the standings."),
        "params": {"year": _YEAR, "round": _ROUND},
        "required": ["year", "round"],
    },
    {
        "name": "f1_archive_race",
        "summary": "A race from 1996-2022, before the live-timing feeds.",
        "description": (
            "Results, lap-by-lap running order, lead changes and laps led "
            "for the seasons the modern feeds do not cover. Pit stops are "
            "included from 2011. The reply carries a 'coverage' block "
            "naming exactly what that era does and does not hold, so an "
            "absent field is never mistaken for a zero. Use f1_race_story "
            "for 2023 onward — it knows strictly more."),
        "params": {"year": _YEAR, "round": _ROUND},
        "required": ["year", "round"],
    },
    {
        "name": "f1_closest_titles",
        "summary": "Championships ranked by how close they finished.",
        "description": (
            "The smallest title margins in history, measured both in points "
            "and relative to what a win was worth that season — the only "
            "way seasons decades apart compare honestly, since two points "
            "in 1958 is most of a win and two points today is not."),
        "params": {"top": {"type": "integer",
                           "description": "How many seasons to return."}},
        "required": [],
    },
    {
        "name": "f1_season_shape",
        "summary": "How a championship unfolded, round by round.",
        "description": (
            "Each contender's running points total, who led after every "
            "round, and where the lead changed hands. Two seasons can end "
            "on the same margin and look nothing alike; this is what tells "
            "a procession from a fight."),
        "params": {"year": _YEAR},
        "required": ["year"],
    },
    {
        "name": "f1_highlights",
        "summary": "The stretches of a race worth watching.",
        "description": (
            "Windows where the timing feed's own passing signals cluster, "
            "ranked by density. An editing index rather than a verdict — "
            "it says where cars were changing state, not that a pass "
            "completed. 2023 onward."),
        "params": {"year": _YEAR, "round": _ROUND},
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


def _tyres(year, round, **_):
    from .race import load
    from .strategy import circuit_abrasion, stint_degradation
    race = load(year, round)
    return {"stints": stint_degradation(race),
            "circuit_abrasion": circuit_abrasion(race)}


def _deletions(year, round, session="Race", **_):
    from .quality import lap_deletions
    from .race import load_session
    s = load_session(year, round, session)
    return {"session": s.name, "deletions": lap_deletions(s.race_control)}


def _running_order(year, round, **_):
    from .race import load
    race = load(year, round)
    return {"total_laps": race.total_laps, "order": race.running_order(),
            "position_changes": race.position_changes()}


def _battles(year, round, **_):
    from .race import load
    return {"battles": load(year, round).battles()}


def _archive_race(year, round, **_):
    from .archive import load_archive
    return load_archive(year, round).story()


def _title_margins(top=15, **_):
    from .history import title_margins
    return {"closest_titles": title_margins(top=int(top))}


def _season_shape(year, **_):
    from .history import season_shape
    return season_shape(year)


def _highlights(year, round, **_):
    from .feeds import overtake_hotspots
    from .race import load
    return {"hotspots": overtake_hotspots(load(year, round))[:10]}


_HANDLERS = {
    "f1_race_story": _story,
    "f1_race_brief": _brief,
    "f1_session_results": _results,
    "f1_weekend_sessions": _sessions,
    "f1_season_status": _status,
    "f1_standings": _standings,
    "f1_driver_career": _career,
    "f1_data_quality": _quality,
    "f1_tyre_wear": _tyres,
    "f1_deleted_laps": _deletions,
    "f1_running_order": _running_order,
    "f1_battles": _battles,
    "f1_archive_race": _archive_race,
    "f1_closest_titles": _title_margins,
    "f1_season_shape": _season_shape,
    "f1_highlights": _highlights,
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
