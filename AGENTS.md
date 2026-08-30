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
| `http.py` | cached HTTP, TTL policy, BOM-safe, 0.5s pacing, 429/5xx backoff, stale-on-error | `get_json`, `enable_cache`, `cache_info`, `clear_cache` |
| `schedule.py` | season calendar, settle window, what is due to run | `season`, `status`, `due` |
| `sources/openf1.py` | race data REST client (2023+) | `get`, `resolve_race` |
| `sources/livetiming.py` | official archive: session paths + `.jsonStream` | `api_path`, `fetch_stream`, `deepmerge` |
| `sources/jolpica.py` | historic results, 1950→now | `get`, `paged` |
| `sources/multiviewer.py` | circuit geometry | `circuit` |
| `race.py` | **native `Race` object** — the main entry | `load(year, round)`, `Race.story()` |
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
5. **Cache by mutability, never blanket.** Completed-session data is
   immutable (`TTL_FOREVER`); schedules and standings must expire
   (`TTL_SCHEDULE` 6h, `TTL_STANDINGS` 1h). A permanently cached calendar
   hides cancelled rounds for a whole season. New endpoints must declare
   which they are.
6. **Numbers carry their evidence.** `win_probabilities` returns the base
   rate window, sample size and per-driver reasoning. Keep that contract
   for any new estimate.
7. **Models never calculate race facts.** Narration receives preformatted
   structured facts. Every generated draft must pass the numeric and driver
   code whitelist; only verified exact matches may enter the local cache.

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
  (45) is the wait before a race is safe to publish.
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
lead the most laps (31 vs the runner-up's 32). Expected values there were
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
