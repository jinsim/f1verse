# f1verse

[![PyPI](https://img.shields.io/pypi/v/f1verse.svg)](https://pypi.org/project/f1verse/)
[![Python](https://img.shields.io/pypi/pyversions/f1verse.svg)](https://pypi.org/project/f1verse/)
[![Tests](https://github.com/jinsim/f1verse/actions/workflows/test.yml/badge.svg)](https://github.com/jinsim/f1verse/actions/workflows/test.yml)
[![Dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)](https://github.com/jinsim/f1verse/blob/main/pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**The story layer for Formula 1 data.** Data libraries fetch and tidy —
f1verse tells you *what happened*: lead changes, laps led, event timelines,
stint strategy, race pace, and a live championship projection.

**Zero dependencies.** Standard library only. Seasons 2023 onward;
historic records reach back to 1950.

```bash
pip install f1verse
```

```python
import f1verse

race = f1verse.load(2026, 12)        # year, round — no other library needed

race.laps_led()      # {'ANT': 32, 'NOR': 31, 'HAM': 9}
race.leader_runs()   # [{'abbr': 'NOR', 'from': 1, 'to': 4}, ...]
race.results()[7]    # {'abbr': 'HUL', 'gap': '+1 LAP', ...}
race.race_pace()     # median pace — pit/SC/VSC laps excluded by default
race.story()         # one call, whole story, plain JSON

race.championship_prediction()   # per-lap "if it ended now" title projection
race.team_radio()                # timestamped clip URLs (nothing downloaded)
```

### Give it to an AI agent

f1verse ships its own MCP server. No install step, no dependencies:

```json
{"mcpServers": {"f1verse": {"command": "uvx", "args": ["f1verse-mcp"]}}}
```

That is the whole setup — the server is standard library only, so it
starts and answers `tools/list` in about 140 ms instead of unpacking a
scientific stack into a throwaway environment first. Eight tools, not
eighty: a model picks the right one.

For any other LLM pipeline, the library describes itself:

```python
f1verse.tools()                  # MCP-dialect JSON schemas
f1verse.tools("openai")          # function-calling dialect
f1verse.call_tool("f1_race_story", {"year": 2026, "round": 12})
```

Errors are written for the caller that has to fix them without reading
this page:

```python
f1verse.call_tool("f1_race_summary", {})
# LookupError: unknown tool 'f1_race_summary' — available: f1_race_story, ...
f1verse.load_session(2026, 12, "Qualy")
# LookupError: ... listing the sessions that weekend actually had
```

### The whole weekend, not just the race

```python
f1verse.sessions(2026, 12)
# Practice 1 · Sprint Qualifying · Sprint · Qualifying · Race

q = f1verse.load_session(2026, 12, "Qualifying")
q.results()[0]
# {'abbr': 'NOR', 'q1': 72.695, 'q1_gap': 0.085, 'q3': 71.163, 'q3_gap': 0.0,
#  'best': 71.163, 'eliminated_in': None, ...}

q.segments()["q1"]
# {'fastest': 'PIA', 'advanced': [...16 codes...], 'eliminated': [...],
#  'cut_margin': 0.022}
```

Each kind gets the classification it actually has. Qualifying gaps are to
the fastest lap **of that segment** — the pole-sitter above was 0.085 s
off in Q1 — because a single "gap to leader" column would misreport the
session. A sprint loads as a `Race`; practice is a best-lap table.

### Is this data safe to publish?

```python
race.quality_report()
# {'state': 'final',            # provisional → settled → final, or corrected
#  'coverage': {'overall': 0.9955, 'sectors': 0.9824, 'compound': 1.0},
#  'missing': ['STR.lap_46.lap_duration', ...],
#  'source_age_seconds': 312,
#  'revisions': [],             # source rewrites this install has observed
#  'crosscheck': {...},
#  'publishable': True}
```

`crosscheck` answers *do independent sources agree*. `quality_report` adds
the three things that verdict is silent about: how complete the data is,
how old the copy is, and whether the classification is still provisional.

The chequered flag is not the final classification — scrutineering
disqualifications and penalties land hours later and **rewrite rows in
place**. So the rows the stewards can change are not cached forever until
the session is final, and any change that is seen is recorded:

```python
before = race.snapshot()          # hashed, comparable, JSON — you persist it
...
f1verse.diff(before, race.refresh().snapshot())
# {'changed': True,
#  'changes': [{'abbr': 'HAM', 'field': 'position', 'before': 4, 'after': None},
#              {'abbr': 'HAM', 'field': 'gap', 'before': '+8.1s', 'after': 'DSQ'}]}

f1verse.revisions()               # every source rewrite observed, with the
f1verse.vintage(rec)              # superseded body when it was small enough
```

There is deliberately no `as_of=` time travel: f1verse can tell you what
it sees now and when it saw a value change, not reconstruct a value
nobody here ever fetched.

### Beyond a single race

```python
f1verse.career("max_verstappen")
# {'starts': 245, 'wins': 71, 'podiums': 131, 'poles': 48, ...}  1950-present

f1verse.milestones("max_verstappen")
# [{'stat': 'poles', 'current': 48, 'target': 50, 'remaining': 2}]

f1verse.circuit_profile(2026, 13)
# corners, marshal sectors, track outline, and pit loss split by track state
# {'normal': 25.43, 'sc': 16.11, 'vsc': 18.4}  <- what an undercut costs here
# plus historic record: 75 races held, pole-to-win rate 0.30

f1verse.head_to_head(2026)
# teammate quali/race scores per constructor

f1verse.standings(2026)
```

### Running this on a schedule

```python
f1verse.status(2026)
# {'latest_race': {'round': 12, 'meeting': 'Dutch Grand Prix'},
#  'next': {'round': 13, 'session': 'Practice 1'}, 'next_in_hours': 125.7}

f1verse.due(2026, processed=[...session keys you already handled...])
# sessions finished, settled (45 min past the flag) and not yet processed —
# nothing published twice, nothing missed after downtime
```

Caching is policy-driven, not blanket: lap and telemetry data is immutable
and cached forever, schedules expire every few hours — a calendar cached
for a season would hide a cancelled round for the rest of the year — and
rows the stewards can still rewrite expire until the session is final.
`f1verse.cache_info()` and `f1verse.clear_cache(older_than=...)` are there
for operators; `clear_cache` never drops the revision journal.

### Telemetry, track position, conditions

```python
f1verse.lap_telemetry(race, "NOR", 40)
# per-sample speed, throttle, brake, gear, RPM and DRS state for one lap

f1verse.lap_trace(race, "NOR", 40)      # x/y/z coordinates of that lap
f1verse.top_speeds(race)                # fastest reading per driver

f1verse.weather_summary(race)
# {'track_c': {'min': 25.8, 'max': 38.2}, 'rain': True, 'samples': 191}
```

Telemetry is high-frequency, so these take a bounded window and filter
server-side rather than downloading a session and trimming it locally.

### Grounded narration

```python
facts = f1verse.race_facts(race)       # all numbers computed and formatted here
f1verse.brief(race)                    # deterministic text, no model required

result = f1verse.narrate(
    race,
    generate=lambda prompt: my_model(prompt),
    cache_dir=".cache/narration",
)
# {'text': '...', 'source': 'generated' | 'cache' | 'template', ...}
```

`narrate` accepts any text-generation callback; f1verse has no model SDK
dependency. Drafts are checked against the structured fact sheet. Unknown
numbers and driver codes are rejected, generation is retried at most twice,
and a deterministic summary is returned if verification still fails. The
optional cache is exact-match only and stores verified text.

### Predictions, pit-stop verdicts, official documents

```python
f1verse.win_probabilities({"NOR": 1, "ANT": 2, "RUS": 3},
                          year=2026, upto_round=12, circuit_id="monza")
# every probability ships with its own evidence:
#   grid base rate measured over 233 real races (pole wins 54.1%)
#   blended with that circuit's pole-to-win conversion (Monza: 0.30)
#   scaled by recent form (average finish over the last 5 rounds)

f1verse.pit_exchanges(race, pit_loss_s=22.74)
# [{'lap': 17, 'driver': 'RUS', 'rival': 'PIA', 'verdict': 'worked',
#   'gain_s': 3.54}, ...]
# neutralised laps (red flag / SC / VSC) and same-lap covering stops are
# excluded — calling those undercuts would be wrong

f1verse.fia_documents(2026)          # stewards' decisions, classified
f1verse.power_unit_documents(2026)   # "who changed which engine part"
```

## Why this exists

Raw timing data needs a lot of domain knowledge before it means anything:

- **Classified gaps are not comparable across lapped cars.** A car one lap
  down can show a smaller number than one that finished ahead on the lead
  lap. → `format_gap` applies the broadcast convention (`+1 LAP`).
- **"Who led the race" has to be derived.** Lead changes, laps led and the
  moments they happened are not published as such.
  → `leader_runs`, `laps_led`, `timeline`.
- **Race pace needs rules**, not just a threshold: in/out laps and laps run
  under SC/VSC have to go, or the number is meaningless.
  → `race_pace` applies them by default.
- **Web and video pipelines need plain JSON.** Every f1verse output is
  JSON-safe Python, ready to serialise.
- **Data quality should be checkable in code**, not read from logs.
  → `crosscheck` and `quality_report` return structured verdicts.
- **Results change after the flag.** A cache that treats a classification
  as immutable makes a stewards' decision invisible.
  → revisable rows expire until the session is final; changes are recorded.

## Additional live-timing feeds

The official live-timing archive publishes several feeds that are rarely
surfaced. f1verse parses three of them, with the same caching and
rate-limit etiquette as the rest of the library:

```python
f1verse.championship_prediction(session)
# per-lap "if the race ended now" projection of both championships,
# including the moments the projected champion changed

f1verse.team_radio(session)
# timestamped team-radio clips: [{'t', 'utc', 'driver_number', 'url'}]
# URLs only — nothing is downloaded or redistributed

f1verse.timing_stats(session)
# personal bests, best sectors, speed-trap figures
```

## Running continuously

See **[OPERATIONS.md](OPERATIONS.md)** for caching policy, rate limits and
scheduling.

## Tests

```bash
pip install -e ".[test]" && pytest -q
```

## Sources

| Layer | What it gives |
|---|---|
| Race data | laps, stints, pits, positions, results, overtakes |
| Live-timing archive | championship projection, team radio, timing stats |
| Historic records | careers, circuit records, standings — 1950 onward |
| Circuit geometry | track outline, corners, marshal sectors, pit loss |

All are public endpoints, read at runtime. See `src/f1verse/sources/` for
the exact hosts and `LICENSE` notes where attribution applies.

## Design rules

1. **Zero required dependencies.** The native loader reads public REST
   endpoints and the official live-timing archive directly, with its own
   on-disk cache and polite pacing.
2. **Everything returned is plain JSON-safe Python.**
3. **F1 domain rules are defaults, not options.**
4. **Cross-checked where possible** — lapped-car gaps, for instance, are
   computed by convention *and* confirmed against a second source.
5. **Code only.** No timing data, media, or images are bundled or
   redistributed; data is fetched by the end user.

## Roadmap

- Broader cross-validation coverage
- Comparison primitives (lap vs lap, stint vs stint) with sample counts
- Deviation detection: expected range, actual, evidence
- Localisation packages


---

*Unofficial fan project. Not affiliated with, endorsed by, or associated
with Formula 1, FIA, FOM, or any F1 team. F1, FORMULA 1 and related marks
are trademarks of Formula One Licensing BV. This library contains code
only — no timing data, media, or images are included or redistributed;
data is fetched by the end user from publicly accessible endpoints,
subject to the respective providers' terms.*
