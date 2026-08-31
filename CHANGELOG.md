# Changelog

Versions follow [semantic versioning](https://semver.org). Published
releases are immutable; a fix ships as a new patch version.

## 0.12.0

**The library stops pretending F1 began in 2023, and learns to read a race
lap by lap.**

### Twenty-seven more seasons

- **`archive.py`.** `load_archive(2008, 18)` returns the 2008 Brazilian Grand
  Prix — results, lap-by-lap running order, lead changes, laps led — for the
  seasons the live-timing feeds never covered. Lap times reach back to 1996
  and pit stops to 2011, which is what the historic record actually holds;
  the 2023 boundary was a property of one source, not of the sport.
- **Coverage is stated, not implied.** Every return value carries a `coverage`
  block naming what that era holds. 2008 has no stint data anywhere, so
  `ArchiveRace` has no `stints()` at all rather than an empty dict that reads
  like "nobody pitted". A fabricated stint is worse than a missing one.
- **`jolpica.race_rows`, `lap_timings`, `pit_stops`.** Jolpica's `laps` and
  `pitstops` paginate *inside* a single race, so the generic pager — which
  counts races — walked forever and tripped its own guard. These walk the
  inner list instead.

### How a race unfolded

- **`Race.running_order`.** Who was where at the end of every lap, from the
  only ordering the lap feed actually witnesses. A retirement shortens the
  list rather than freezing a ghost in place.
- **`Race.position_changes`.** Per lap, how much the order churned and who
  made the largest single gain. Laps where the field simply strings out score
  zero, so the peaks are the laps worth watching.
- **`Race.battles`.** Pairs that held consecutive positions within 1.5 s for
  at least three laps, with the closest the gap got. A scrap for eighth that
  ran a third of the race never appears in a classification; it is often the
  best part of the afternoon.

### Seasons against each other

- **`title_margins`.** Championships ranked by how close they finished — in
  points, and relative to what a win was worth that season. Points systems
  changed repeatedly, so a raw margin cannot compare eras: one point in 1958
  was most of a win, and two points today is not.
- **`season_shape`.** Each contender's running total, who led after every
  round, and where the lead changed hands. Two seasons can end on the same
  margin and look nothing alike.

### Undercuts against a real yardstick

- **`circuit_pit_loss`** is now wired into `pit_exchanges`, which had been
  reporting `pit_loss_reference_s: null` while the parser for it already
  existed. Verdicts carry `share_of_pit_loss`, so "gained 2.1 s" is read
  against the ~23 s the stop cost — and the safety-car and VSC figures are
  there for why a neutralised stop is cheap.

### The feed's own passing signals

- **`overtake_signals`, `overtake_hotspots`.** `DriverRaceInfo` publishes an
  `OvertakeState` per car that barely ever changes — about a hundred
  transitions in nineteen thousand records. That sparsity is the value: the
  transitions are a free index of the moments worth looking at, independent
  of any passing logic of our own. Read as "something happened here", not as
  a completed pass.

### Also

- Six new agent tools: `f1_running_order`, `f1_battles`, `f1_archive_race`,
  `f1_closest_titles`, `f1_season_shape`, `f1_highlights` — sixteen in all.
- Two invariants added to `AGENTS.md`: an era's limits are stated and never
  estimated, and lap keys stay integers internally (`jsonsafe` stringifies
  them, and `"10"` sorts before `"2"`).

## 0.11.1

The MCP registry verifies that whoever publishes a listing also owns the
package it points at, by looking for an ownership marker in the README as
PyPI serves it. A published README is immutable, so carrying that marker
takes a release of its own. `tests/test_docs.py` now holds the marker to
the name in `server.json`.

## 0.11.0

**f1verse is now callable by agents, not only by people — and it reaches the
wire it used to read second-hand.**

### Live timing, and lap tables rebuilt from it

- **`sources/liveclient.py`.** The official SignalR live feed over a WebSocket
  written in the standard library. Connecting requires three undocumented
  courtesies — the load balancer's affinity cookie from a pre-flight request,
  the official application's user agent, and an invocation id on the
  subscription — and all three now live in one place. `record` stamps every
  frame with its arrival time, `replay` runs a session back at true speed, and
  `run` survives dropped sockets and session turnover.
- **`sources/timing.py`.** `laps_from_stream` rebuilds per-driver lap tables
  from the raw patch stream, whose arrival order lies. The grace window, the
  credibility ceiling, blank-versus-unknown, and earliest-witness lap ends are
  encoded with their reasons; every lap row carries its provenance.
- **`_clock.py`.** One parser for every wire clock, lap and wall-time shape.

### Strategy and stewards

- **Tyre life.** `stint_degradation`, `circuit_abrasion`, `tyre_outlook` and
  `fuel_normalised`. Rates are fitted to fuel-normalised clean laps only, and a
  stint with too few of them reports that instead of a number fitted to noise.
- **`lap_deletions`.** Every lap time race control struck out, with the reason
  and whether a reinstatement reversed it.
- **`strategy_rollout`** — seeded, reproducible strategy comparisons.
- **`gaps.reconcile`** — a gap series that keeps its provenance.
- **Per-host hourly request budgets** in `http.py`.

### The agent surface

- **MCP server.** `uvx --from f1verse f1verse-mcp` starts a Model Context
  Protocol server over stdio. It is implemented in the standard library
  rather than on the MCP SDK, so the zero-dependency rule holds and the
  process answers `tools/list` in roughly 140 ms.
- **Ten tools**, including `f1_tyre_wear` and `f1_deleted_laps`.
- **Tool catalogue.** `f1verse.tools()` returns MCP-dialect JSON schemas,
  `f1verse.tools("openai")` returns function-calling schemas, and
  `f1verse.call_tool(name, arguments)` executes one. The MCP server serves
  the same catalogue, so the two surfaces cannot drift apart.
- **Errors written to be read by machines.** An unknown tool name lists the
  tools that exist, a missing argument names it, an unexpected argument
  names what is accepted.
- **Documentation site** at <https://jinsim.github.io/f1verse/>, one page per
  question, generated by `scripts/build_docs.py`.
- **`llms.txt` and `llms-full.txt`** so a language model can take in the
  whole library in one fetch.
- **`server.json`** for the Model Context Protocol registry.
- New top-level exports: `stint_degradation`, `circuit_abrasion`,
  `tyre_outlook`, `fuel_normalised`, `lap_deletions`, `strategy_rollout`,
  `reconcile_gaps`.
- Packaging metadata: Beta status, per-version Python classifiers,
  documentation/issues/changelog URLs, `f1verse-mcp` console script.

No behaviour of the existing API changed.

## 0.10.0

Observable corrections and per-session quality: `quality_report`,
`snapshot`/`diff`, the revision journal, and the `Session` base class that
gives every kind of session on a weekend the classification it actually has.

## 0.9.1

Release pipeline hardening.

## 0.9.0

Grounded narration and safer retrieval.
