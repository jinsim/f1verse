# AGENTS.md — f1verse

Machine-facing map of this repository. Read this before changing anything.

## What this is

`f1verse` is the **story layer** for Formula 1 data: it answers "what
happened in this race" and "what does it mean historically", built on top
of public data sources.

- Language: Python ≥3.9. **Zero dependencies** (standard library only).
- Public repo: https://github.com/jinsim/f1verse · Apache-2.0 · unofficial fan project.

## Module map

| File | Responsibility | Key entry points |
|---|---|---|
| `http.py` | cached HTTP, TTL policy, BOM-safe, 0.5s pacing, per-host hourly budgets, 429/5xx backoff, stale-on-error, revision journal | `get_json`, `enable_cache`, `cache_info`, `clear_cache`, `revisions`, `vintage`, `entry_meta` |
| `schedule.py` | season calendar, settle window, session lifecycle, what is due to run | `season`, `status`, `due`, `lifecycle` |
| `sources/openf1.py` | race data REST client (2023+) | `get`, `resolve_race` |
| `sources/livetiming.py` | official archive: session paths + `.jsonStream`, list-index patches, `.z` channels | `api_path`, `fetch_stream`, `deepmerge`, `unpack_z` |
| `sources/timing.py` | lap tables rebuilt from the raw timing patch stream (grace window, credibility ceiling, blank-vs-unknown, earliest-witness lap ends) | `laps_from_stream` |
| `sources/liveclient.py` | live SignalR feed over a stdlib WebSocket; stamped recorder and replay | `LiveFeed`, `decode`, `record`, `replay`, `run` |
| `_clock.py` | wire-format clock/lap/wall-time parsing, every feed shape | `clock_seconds`, `lap_seconds`, `wall_time` |
| `sources/jolpica.py` | historic results and circuit directory, 1950→now; lap times 1996+, pit stops 2011+ | `get`, `paged`, `circuits`, `race_rows`, `lap_timings`, `pit_stops` |
| `sources/multiviewer.py` | circuit geometry with revisable-layout cache policy | `circuit` |
| `session.py` | **`Session` base** — any session of a weekend; per-kind classification | `Session`, `Qualifying`, `Practice` |
| `race.py` | **native `Race` object** — the main entry; lap-by-lap order, churn, battles | `load(year, round)`, `load_session`, `sessions`, `Race.story()`, `running_order`, `position_changes`, `battles` |
| `archive.py` | **pre-2023 races** — 1996+ lap times, 2011+ pit stops, with an explicit `coverage` block | `load_archive(year, round)`, `coverage`, `ArchiveRace.story()` |
| `quality.py` | completeness, source age, lifecycle, corrections, steward lap deletions | `quality_report`, `snapshot`, `diff`, `lap_deletions` |
| `gaps.py` | broadcast gap convention; provenance-preserving gap series | `format_gap`, `reconcile` |
| `crosscheck.py` | publish gating across independent sources | `crosscheck(race)` |
| `history.py` | careers, milestones, circuit records, standings, cross-season rankings | `career`, `milestones`, `circuit_history`, `standings`, `title_margins`, `season_shape` |
| `circuit.py` | current-layout geometry + history, full venue directory, evidence-labelled shape diagnostics | `profile(year, round)`, `directory`, `layout_diagnostics` |
| `teammates.py` | teammate head-to-head scores | `head_to_head(year)` |
| `predict.py` | win probabilities from measured base rates; seeded strategy rollouts; championship projection with its own backtest | `win_probabilities`, `grid_base_rates`, `strategy_rollout`, `title_scenarios`, `championship_projection`, `backtest_projection` |
| `strategy.py` | undercut/overcut verdicts against real pit loss; fuel-normalised tyre life and outlook | `pit_exchanges(race)`, `circuit_pit_loss`, `stint_degradation`, `circuit_abrasion`, `fuel_normalised`, `tyre_outlook` |
| `reference.py` | published circuit facts (curated over Wikidata), the audit that re-derives them from telemetry, and the review that keeps them current | `facts`, `known`, `audit`, `stale`, `review` (exported as `circuit_facts`, `circuit_audit`, `circuit_review`, `circuit_facts_stale`) |
| `sources/formula1.py` | official circuit specifications, swept from the season index (curation tool, not a query path) | `season_slugs`, `circuit_specs`, `season_specs` |
| `sources/wikidata.py` | circuit specifications from the CC0 upstream, reached via the article each circuit already names | `entity_id`, `circuit_facts` |
| `survey.py` | circuit measured from its own telemetry (public entry `circuit_survey`) — elevation, overtaking zones, braking/throttle character, used width and a relative camber index | `elevation`, `corner_dossier`, `overtaking_zones`, `character`, `driven_corridor`, `drs_zones`, `survey` |
| `telemetry.py` | car data and track position, per lap | `lap_telemetry`, `lap_trace`, `top_speeds` |
| `weather.py` | session conditions | `readings`, `summary` |
| `narration.py` | structured fact sheet, deterministic brief, verified optional generation | `race_facts`, `brief`, `narrate`, `verify` |
| `fia.py` | FIA decision-document index; season chosen by id, walks the event list | `documents`, `events`, `power_unit_documents` |
| `feeds.py` | additional live-timing feeds; the feed's own passing signals | `championship_prediction`, `team_radio`, `timing_stats`, `overtake_signals`, `overtake_hotspots` |
| `_json.py` | everything public passes through here | `jsonsafe` |
| `_tools.py` | agent tool catalogue — one source for schemas and dispatch | `catalog`, `call` (exported as `tools`, `call_tool`) |
| `mcp.py` | MCP server: stdlib JSON-RPC 2.0 over stdio, `f1verse-mcp` | `handle`, `serve`, `main` |

## Invariants — do not break these

1. **Zero dependencies.** Never add a non-standard-library import. If a
   third-party value can reach `jsonsafe`, guard the import so the module
   still loads without it.
2. **Every public return value is JSON-safe.** Route new outputs through
   `jsonsafe`. `json.dumps(result)` must never raise.
3. **No data redistribution.** Fetch at runtime; never bundle timing data,
   PDFs, images or audio. Team radio and FIA docs are returned as URLs.
4. **Domain rules are defaults, not options.** Pace excludes pit/SC/VSC
   laps; lapped cars show `+1 LAP`; undercut detection excludes neutralised
   laps. Do not make correctness opt-in.
5. **Cache by mutability, never blanket.** Lap and telemetry data is
   immutable (`TTL_FOREVER`); schedules and standings must expire
   (`TTL_SCHEDULE` 6h, `TTL_STANDINGS` 1h). A permanently cached calendar
   hides cancelled rounds for a whole season. New endpoints must declare
   which they are.
6. **A classification is not immutable until it is final.** Endpoints in
   `openf1.REVISABLE` (`session_result`, `race_control`, `starting_grid`,
   `stints`, `pit`) are cached only `TTL_PROVISIONAL` until
   `schedule.FINAL_HOURS` past the session end. Caching them forever makes
   a disqualification invisible for the life of the cache — the failure is
   silent and lands in published output. Any endpoint a steward can rewrite
   goes in that set.
7. **An unavailable check is not a passing check.** `crosscheck` returns
   `skipped` when its independent source does not exist for a session
   (sprints have no `/overtakes`). Never let "nothing was compared" and
   "nothing disagreed" produce the same verdict.
8. **Every change to a cached body is journalled.** `http` writes the
   superseded copy and a record to `_revisions.jsonl`; `clear_cache` must
   never delete it. It is the evidence a correction notice is written from.
9. **Possible and likely are different claims.** `title_scenarios`
   answers *can this still happen* with arithmetic — maximum points
   remaining is a fact. `championship_projection` answers *how likely*
   with a model. Never let one be printed as the other, and never let a
   projection imply a driver is eliminated when the arithmetic says
   otherwise.
10. **Numbers carry their evidence.** `win_probabilities` returns the base
   rate window, sample size and per-driver reasoning. Keep that contract
   for any new estimate.
11. **Models never calculate race facts.** Narration receives preformatted
   structured facts. Every generated draft must pass the numeric and driver
   code whitelist; only verified exact matches may enter the local cache.
12. **One catalogue, one dispatcher.** `_tools.py` is the only definition of
   the agent surface: the MCP server calls it and so does `f1verse.tools()`.
   Never hand-write a second tool list — schemas and behaviour cannot be
   allowed to drift. A new tool needs a `_SPECS` entry *and* a `_HANDLERS`
   entry; `tests/test_tools.py` enforces that they match.
13. **Errors are read by machines.** A wrong tool name lists the real names,
   a missing argument names it, an unknown session lists the sessions that
   weekend had. An agent recovers from the message or not at all — never
   raise a bare `KeyError` from a public entry point.

14. **An era's limits are stated, never implied.** `archive.py` covers
   1996-2022, where lap times exist from 1996 and pit stops from 2011.
   Every return value carries a `coverage` block naming what that season
   actually holds. A field the era never recorded is absent with a reason,
   never defaulted to zero or estimated from something else — a fabricated
   stint is worse than a missing one.
15. **Integer lap keys stay integers inside.** `jsonsafe` stringifies dict
   keys, and `"10"` sorts before `"2"`. Anything that iterates laps uses
   the private integer-keyed helper (`Race._order`, `ArchiveRace._order`);
   only the public wrapper passes through `jsonsafe`.
16. **Curated facts are never written from memory.** An entry in
   `data/circuits.json` carries the source it was read from and the date it
   was checked, and a circuit nobody has verified stays absent —
   `reference.facts` returning `None` says "nobody looked", which is a
   different and more useful statement than a plausible wrong number.
   Automated refreshes may only write `reference.SWEPT`.
17. **The library is consumer-blind.** f1verse has no knowledge of any
   downstream application, sibling workspace, private dataset, brand, or
   publishing pipeline. Features enter this repository only when they stand
   alone for general Python or MCP users. Never inspect or import from outside
   this checkout, hard-code a developer path, or shape a public API around one
   unnamed consumer.

## Source behaviour worth knowing

- **The FIA documents site picks a season by id, not by the year in the URL.**
  The year segment is decorative: `season-2026-2071` returns 2025's documents
  with a 200 and a full page. Getting the id wrong therefore fails *silently*,
  which is why `fia._SEASON_KEY` is explicit and an unknown year raises rather
  than falling back to a default. Verified ids: 2020=1059, 2021=1108,
  2022=2005, 2023=2042, 2024=2043, 2025=2071, 2026=2072.
- **A FIA season landing page only shows the most recent event.** Indexing a
  whole season means walking the event dropdown, one request per event, which
  is what `fia.documents()` does — hence every row carries its `event`.
- Classified time values are **not comparable for lapped cars** — a
  lapped P8 can print a smaller number than P7. Always branch on `Status`.
- `/meetings` **includes cancelled rounds**; filter `is_cancelled`
  or round numbering silently shifts.
- `/overtakes` records **on-track passes only** — a lead taken in a pit
  cycle is a lead change but not an overtake. `crosscheck` therefore
  asserts subsequence containment, not equality.
- Historic qualifying rows use `QualifyingResults`; race rows use `Results`.
- Season-wide aggregation **will** hit HTTP 429. `http.py` backs off; do
  not paper over it with sleeps at call sites.
- `pitLoss` is a dict split by track state
  (`normal` / `sc` / `vsc`), not a scalar.
- Timing data is not final at the chequered flag; `schedule.SETTLE_MINUTES`
  (45) is the wait before a race is safe to publish, and
  `schedule.FINAL_HOURS` (72) is when the classification stops being
  treated as revisable. Appeals run longer than that — `Race.refresh()`
  is the escape hatch, and it journals whatever it finds.
- **Qualifying `gap_to_leader` is per segment, not to pole.** Both
  `duration` and `gap_to_leader` come back as three-element lists, one per
  segment, each relative to that segment's fastest lap. `None` in slot *i*
  means the driver was knocked out before it. A race-shaped formatter
  crashes on the list; a naive one reports the pole-sitter as 0.085 s off
  their own pole time.
- `/overtakes` is not published for sprints — 404, not an empty list.
- `/sessions` rows carry no meeting name — join from `/meetings`.
- Range parameters are `name>=value`, not `name=value`; `urlencode` mangles
  them into a 404. `http.get_text` builds those pairs by hand.
- Telemetry endpoints return tens of thousands of rows per session —
  always bound the window and filter server-side.
- `.jsonStream` files are BOM-prefixed and send one snapshot
  followed by partial patches — merge with `deepmerge`.

- Jolpica's `laps` and `pitstops` paginate **inside a single race**, so the
  generic `paged` helper (which counts races) never makes progress and
  trips its own guard. Use `jolpica.race_rows` / `lap_timings` / `pit_stops`.
- `DriverRaceInfo.jsonStream` carries `OvertakeState` per car. It barely
  ever changes — a race of ~19,000 records turns over about a hundred
  times — which is exactly what makes the transitions a usable highlight
  index. The static `.json` is only the final snapshot and is useless for
  this; the stream is required.
- Points systems changed repeatedly, so raw title margins do not compare
  across eras. `title_margins` also reports the gap relative to what a win
  was worth that season.

## Circuit knowledge

Three independent layers answer "what is this circuit". They are ordered by
trust, and each exists because the ones beside it fail differently.

| Layer | Where | Good at | Fails at |
|---|---|---|---|
| curated | `data/circuits.json` | surveyed facts a human checked | going silently stale |
| upstream | `sources/wikidata.py` (CC0) | breadth — 58 of 78 venues carry a length | crowd-sourced, gaps on new and street circuits |
| measured | `survey.py` | noticing that either of the others is wrong | being precise enough to publish |

`reference.facts(name, article)` merges the first two **field by field** and
returns `provenance` saying which layer each value came from.
`circuit.profile(measure=True)` adds the third plus the tyre surface reading,
and `reference.audit` reports where measurement and record disagree — as a
disagreement, never a culprit.

### Keeping it current

`scripts/refresh_circuits.py` with no argument sweeps **the season running
now**, so a new year needs no edit. It joins official event pages to sessions
on the `meetingKey` both feeds share — an exact join, which replaced fuzzy
name matching that could not separate three United States races or two
spellings of Lusail. It prints a diff (NEW / CHANGED / STALE / SKIPPED) and
writes only with `--write`: a moved length is either a rebuilt circuit or a
parse broken by a redesign, and only a person tells those apart.
`reference.stale()` names entries unchecked for longer than a season, and
every audit carries `checked_age_days`.

### Traps, each found by being wrong first

- **Secondary reports are not sources.** They copy each other, so agreement
  between them is one claim repeated. Madrid circulated as 5474 m against an
  official 5416 m; Singapore as 4928 and 4940 m against 4927 m.
- **Fields whose sources disagree are left out**, not picked. An absent field
  audits as `unchecked`, and the measurement is then free to cast a vote.
- **A sweep may only touch `reference.SWEPT`.** Corner counts and notes are
  human-owned; the official pages do not publish them and an automated
  refresh must never clear them.
- **Feeds spell circuits differently** (Lusail/Losail, Singapore/Marina Bay,
  Monte Carlo/Monaco, Spielberg/Red Bull Ring). Entries carry `aliases`;
  keying a new entry by the wrong name makes it dead at runtime.
- **A Grand Prix can be held in another country.** The 2026 Bahrain Grand
  Prix runs at Sepang in Malaysia — the championship's own event name says
  so. A feed reporting a Malaysian circuit for it is correct, not broken.
- **An official page embeds the event more than once**, with different
  fields in each copy, so the copies must be merged rather than chosen
  between. There is no separate API — the site renders on the server.
- **The season index is ordered from today**, not from round one, so
  position in it says nothing about round number.

### What the cars can and cannot measure

- Verified at Zandvoort: measured lap distance within 0.4% of the published
  4.259 km, corner count exact, per-corner lateral load in the 4-5 g band a
  Formula 1 car really sustains.
- The **camber index is not an angle.** It locates banking and gives its
  direction but reads about a quarter of the true slope, because noise in a
  car's measured lateral position drags any fitted slope toward zero.
  Banking is not obtainable from public data at all: a 30 m DEM pixel
  swallows the whole track width, and precise scans are commercial.
- **Which laps are read decides what is measured.** Quick laps are all the
  same line, so they measure a road a foot wide and never open DRS; opening
  laps spread the field across the road. Pit-lane samples must be excluded
  or the fit reports impossible geometry.
- **From 2026 there is no DRS.** The channel remains in the schema and is
  never set, so an empty result is a regulation change, not weather.
  `survey.overtaking_zones` is the era-independent successor.
- `circuit_abrasion` clamps its factor to [0.7, 1.4]; `at_limit` marks a
  clamped reading, which is a floor rather than a measurement.


## Operating

Caching policy, rate-limit behaviour and run scheduling are documented in
**[OPERATIONS.md](OPERATIONS.md)**. In short: cache by mutability (completed
sessions forever, schedules 6h, standings 1h), wait
`schedule.SETTLE_MINUTES` after a session ends before processing it, and
gate publication on `crosscheck()`.

Local working notes belong in `notes/` or `*.local.md`, both gitignored —
keep planning, research and product context out of this repository. If
`AGENTS.local.md` exists in this checkout, read it too: it holds machine
context that must not be published.

## Verification

```bash
pytest -q
```

`tests/` pins the library against a reference race, 2026 round 12, chosen
because it exercises the awkward cases at once: a red flag, two VSC
periods, six retirements, lapped finishers, and a winner who did **not**
lead the most laps (31 vs the runner-up's 32). It is also a sprint
weekend, so all five session kinds — and the missing `/overtakes` feed —
are covered by the same fixture.

`tests/test_quality.py` stages a real correction over `file://` URLs, so
the revision journal is exercised offline rather than waiting for the
stewards. Expected values there were
checked by hand against the published classification — if a change breaks
one, the change is wrong until proven otherwise.

`tests/test_gaps.py` runs offline; the reference-race tests fetch once and
cache. CI runs both on 3.9 and 3.12.

## Release

Tag-driven, via PyPI trusted publishing (`.github/workflows/publish.yml`):

```bash
git tag v0.5.0 && git push --tags
```

Requires a one-time pending publisher on pypi.org
(project `f1verse`, owner `jinsim`, workflow `publish.yml`, env `pypi`).
The complete checklist and failure gates are in **[RELEASING.md](RELEASING.md)**.
