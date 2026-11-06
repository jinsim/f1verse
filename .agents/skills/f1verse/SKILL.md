---
name: f1verse
description: Analyse Formula 1 races, strategy, historical comparisons and championship scenarios using f1verse Python or MCP, with source checks and explicit statistical limits. Use for evidence-backed F1 analysis and briefs, not general sports or marketing analytics.
---

# f1verse

Use runtime data to explain what happened and what the evidence supports.
This skill supplies analysis instructions; it does not install the Python
package, connect an MCP server or grant access to upstream services.

## Choose the available interface

- If f1verse MCP is connected, discover its current tools with `tools/list`.
  Read `f1verse://guide` when advertised. Use the actual tool schemas; client
  prefixes may differ, and an older installed version may lack newer tools.
- Otherwise use the Python package: `import f1verse`, inspect
  `f1verse.tools()` and call `f1verse.call_tool(name, arguments)` or native
  Python APIs. Install `f1verse` in the task's environment if needed.
- Fetch at runtime. Do not substitute remembered race results for unavailable
  data. On access failure, use `source_status()` or its advertised MCP tool;
  report missing coverage and actionable errors without exposing credentials.

## Resolve the question

Turn relative dates into an explicit season and round using the current date
and season status. Confirm the session: practice, qualifying, sprint and race
have different classifications. Discover driver and circuit identifiers instead
of guessing them.

For a whole race, start with the story and data quality. Use narrower calls for
unanswered questions rather than fetching the whole weekend repeatedly. For
1996-2022 lap-by-lap analysis use the archive interface and its `coverage` block:
lap times start in 1996 and pit stops in 2011. Historical results reach 1950;
that does not imply telemetry, stints or lap-by-lap coverage for those seasons.

## Build an evidence-backed answer

1. Inspect lifecycle, missing fields, source age, corrections, crosschecks and
   `publishable`. An unavailable or skipped check does not establish agreement.
   Distinguish same-provider checks from independent confirmation.
2. Separate observations, retrospective rankings and model scenarios. Event
   IDs and source lineage let a reader trace claims and recognise corrections;
   replayed events are not new observations. Turning-point rankings and pace
   shifts identify candidates, not causal effects.
3. For pace or strategy, retain the library's pit/SC/VSC exclusions. State
   samples, excluded cases and relevant assumptions. A before/after position
   gain alone does not prove an undercut caused it. For 2026 onward, report raw
   tyre trends unless an explicit fuel scenario supports corrected wear.
4. Keep mathematical title eligibility distinct from model probabilities.
   Report the model's evidence window, sample size and assumptions. Use proper
   scores and same-case baselines for forecast comparisons; corrected-source
   backtests are not records of forecasts issued in the past. Multiple laps,
   drivers or checkpoints from one race/season are dependent observations.
5. Preserve unknowns: absent coverage is not zero, lapped-car gaps are laps,
   qualifying gaps are segment-relative, and empty 2026 DRS readings do not
   establish an active aero or energy mode. Descriptive retirement survival
   is not a calibrated individual failure prediction.

Write the answer at the requested depth, leading with supported findings.
Include the event/session, provisional status when relevant, source evidence,
and material limitations beside the claims they qualify. For generated briefs,
prefer the library's fact-bound rendering; free prose must not introduce race
numbers or driver/value associations that were not verified against the data.

For implementation details and method references, consult the installed
version's [documentation](https://jinsim.github.io/f1verse/) and
[methodology](https://github.com/jinsim/f1verse/blob/main/METHODOLOGY.md).
