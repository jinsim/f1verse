# AGENTS.md — f1verse

Machine-facing map of this repository. Read this before changing anything.

## What this is

`f1verse` is the **story layer** for Formula 1 data: it answers "what
happened in this race" and "what does it mean historically", built on top
of public data sources.

- Language: Python ≥3.9. **Zero dependencies** (standard library only).
- Public repo: https://github.com/jinsim/f1verse · MIT · unofficial fan project.

## Module map

| File | Responsibility | Key entry points |
|---|---|---|
| `http.py` | cached HTTP, TTL policy, BOM-safe, 0.5s pacing, 429/5xx backoff, stale-on-error, revision journal | `get_json`, `enable_cache`, `cache_info`, `clear_cache`, `revisions`, `vintage`, `entry_meta` |
| `schedule.py` | season calendar, settle window, session lifecycle, what is due to run | `season`, `status`, `due`, `lifecycle` |
| `sources/openf1.py` | race data REST client (2023+) | `get`, `resolve_race` |
| `sources/livetiming.py` | official archive: session paths + `.jsonStream` | `api_path`, `fetch_stream`, `deepmerge` |
| `sources/jolpica.py` | historic results, 1950→now | `get`, `paged` |
| `sources/multiviewer.py` | circuit geometry | `circuit` |
| `session.py` | **`Session` base** — any session of a weekend; per-kind classification | `Session`, `Qualifying`, `Practice` |
| `race.py` | **native `Race` object** — the main entry | `load(year, round)`, `load_session`, `sessions`, `Race.story()` |
| `quality.py` | completeness, source age, lifecycle, corrections | `quality_report`, `snapshot`, `diff` |
| `gaps.py` | broadcast gap convention | `format_gap` |
| `crosscheck.py` | publish gating across independent sources | `crosscheck(race)` |
| `history.py` | careers, milestones, circuit records, standings | `career`, `milestones`, `circuit_history`, `standings` |
| `circuit.py` | geometry + history in one profile | `profile(year, round)` |
| `teammates.py` | teammate head-to-head scores | `head_to_head(year)` |
| `predict.py` | win probabilities from measured base rates | `win_probabilities`, `grid_base_rates` |
| `strategy.py` | undercut/overcut verdicts | `pit_exchanges(race)` |
| `telemetry.py` | car data and track position, per lap | `lap_telemetry`, `lap_trace`, `top_speeds` |
| `weather.py` | session conditions | `readings`, `summary` |
| `narration.py` | structured fact sheet, deterministic brief, verified optional generation | `race_facts`, `brief`, `narrate`, `verify` |
| `fia.py` | FIA decision-document index | `documents`, `power_unit_documents` |
| `feeds.py` | additional live-timing feeds | `championship_prediction`, `team_radio`, `timing_stats` |
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
9. **Numbers carry their evidence.** `win_probabilities` returns the base
   rate window, sample size and per-driver reasoning. Keep that contract
   for any new estimate.
10. **Models never calculate race facts.** Narration receives preformatted
   structured facts. Every generated draft must pass the numeric and driver
   code whitelist; only verified exact matches may enter the local cache.
11. **One catalogue, one dispatcher.** `_tools.py` is the only definition of
   the agent surface: the MCP server calls it and so does `f1verse.tools()`.
   Never hand-write a second tool list — schemas and behaviour cannot be
   allowed to drift. A new tool needs a `_SPECS` entry *and* a `_HANDLERS`
   entry; `tests/test_tools.py` enforces that they match.
12. **Errors are read by machines.** A wrong tool name lists the real names,
   a missing argument names it, an unknown session lists the sessions that
   weekend had. An agent recovers from the message or not at all — never
   raise a bare `KeyError` from a public entry point.

## Source behaviour worth knowing

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
