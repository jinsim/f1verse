"""f1verse — the story layer for Formula 1 data.

>>> import f1verse
>>> race = f1verse.load(2026, 12)
>>> race.laps_led()              # {'ANT': 32, 'NOR': 31, 'HAM': 9}
>>> race.story()                 # whole race as JSON-safe dict
>>> race.crosscheck()            # validate before publishing
>>> race.quality_report()        # completeness, age, corrections, verdict
>>> f1verse.load_session(2026, 12, "Qualifying").segments()
>>> f1verse.tools()              # JSON tool schemas for an LLM/agent

Seasons 2023 onward. Historic records, circuits and careers reach back
to 1950.
"""
from . import http
from ._version import __version__
from ._json import jsonsafe
from .feeds import championship_prediction, team_radio, timing_stats
from .gaps import format_gap
from .circuit import profile as circuit_profile
from .crosscheck import crosscheck
from .fia import documents as fia_documents, power_unit_documents
from .history import career, circuit_history, milestones, standings
from .session import SCHEMA_VERSION, Practice, Qualifying, Session
from .race import Race, load, load_session, sessions
from .quality import diff, quality_report, snapshot
from .schedule import due, season, status
from .telemetry import lap_telemetry, lap_trace, top_speeds
from .weather import readings as weather_readings, summary as weather_summary
from .narration import (brief, narrate, prompt as narration_prompt,
                        race_facts, unsupported_numbers, verify)
from .predict import grid_base_rates, recent_form, win_probabilities
from .strategy import pit_exchanges
from .teammates import head_to_head
from ._tools import catalog as tools, call as call_tool

enable_cache = http.enable_cache
cache_info = http.cache_info
clear_cache = http.clear_cache
revisions = http.revisions
vintage = http.vintage
__all__ = ["load", "load_session", "sessions", "Race", "Session",
           "Qualifying", "Practice", "format_gap", "jsonsafe", "enable_cache",
           "cache_info", "clear_cache", "revisions", "vintage",
           "quality_report", "snapshot", "diff", "SCHEMA_VERSION",
           "season", "status", "due",
           "championship_prediction", "team_radio", "timing_stats",
           "crosscheck", "career", "milestones", "circuit_history", "standings",
           "circuit_profile", "head_to_head", "win_probabilities",
           "grid_base_rates", "recent_form", "pit_exchanges",
           "fia_documents", "power_unit_documents", "lap_telemetry",
           "lap_trace", "top_speeds", "weather_readings", "weather_summary",
           "race_facts", "brief", "narrate", "narration_prompt", "verify",
           "unsupported_numbers", "tools", "call_tool"]
