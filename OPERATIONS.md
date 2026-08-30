# Operating f1verse

How to run this continuously without hammering the upstream APIs or
publishing half-finished data.

## Caching is by mutability, not blanket

Lap times never change; schedules do, and so does a classification while
the stewards are still working. A calendar cached for a season would hide
a cancelled round for the rest of the year, so cache policy is chosen per
endpoint class:

| Data | TTL | Constant |
|---|---|---|
| Completed-session laps, positions, telemetry | forever | `TTL_FOREVER` |
| Classification, race control, stints, pits — until final | 15 minutes | `TTL_PROVISIONAL` |
| Schedules — sessions, meetings, season index | 6 hours | `TTL_SCHEDULE` |
| Championship standings | 1 hour | `TTL_STANDINGS` |
| In-progress session data | 1 minute | `TTL_LIVE` |

Callers do not choose: `sources/openf1.py` and `sources/jolpica.py` pick
the policy from the endpoint. If a refresh fails but a stale entry exists,
the stale copy is served — an hour-old schedule beats no schedule.

The rows in `openf1.REVISABLE` drop to `TTL_FOREVER` only once a session
is `final` (`schedule.FINAL_HOURS`, 72 hours past the end). Before that
they are re-checked, because a scrutineering disqualification or a
post-race penalty rewrites them in place hours after the flag — and a
cache that calls them immutable makes that correction invisible.

```python
f1verse.enable_cache("path/to/cache")   # default: ~/.cache/f1verse
f1verse.cache_info()   # {'entries': 107, 'bytes': 2837844, 'revisions': 0}
f1verse.clear_cache(older_than=30*86400)
```

## When a source changes under you

Whenever a re-fetch returns a body different from the cached one, the
superseded copy is kept and the change is appended to `_revisions.jsonl`
inside the cache directory. `clear_cache` never deletes it: it is the
evidence a correction notice gets written from.

```python
f1verse.revisions()          # every change observed, oldest first
f1verse.vintage(record)      # the superseded body, when it was small enough
race.revisions()             # only this session's rows
```

This is a record of what this installation saw, not an archive of every
value that ever existed. There is no `as_of=` parameter, because f1verse
cannot reconstruct a value nobody here ever fetched. To keep a real
ledger, persist `race.snapshot()` yourself and compare with `f1verse.diff`:

```python
before = load_snapshot(key) or race.snapshot()
after = race.refresh().snapshot()      # refresh() forces the revisable rows
change = f1verse.diff(before, after)
if change["changed"]:
    publish_correction(change["changes"])
save_snapshot(key, after)
```

## Rate limits

Season-wide aggregation (`head_to_head`, `grid_base_rates`) will hit HTTP
429. The HTTP layer honours `Retry-After` and backs off exponentially, up
to six attempts. Do not add `sleep` calls at the call site to work around
this — if a job is dying, the backoff is the thing to fix.

Requests are paced at two per second regardless of cache state.

## Knowing when to run

A session's timing data is not final when the chequered flag falls.
`schedule.SETTLE_MINUTES` (45) is the wait before a race is safe to
process; `status()` and `due()` apply it for you.

```python
f1verse.status(2026)
# {'completed': 60,
#  'latest_race': {'round': 12, 'meeting': 'Dutch Grand Prix'},
#  'next': {'round': 13, 'session': 'Practice 1'},
#  'next_in_hours': 125.7,
#  'settle_minutes': 45}

f1verse.due(2026, processed=[...session keys already handled...])
# finished, settled, and not yet processed — nothing published twice,
# nothing missed after downtime
```

A scheduled job therefore looks like:

```python
processed = load_state()                       # your own store
for session in f1verse.due(2026, processed):
    race = f1verse.load(2026, session["round"])
    if not race.crosscheck()["publishable"]:
        continue                               # hold, do not publish
    handle(race.story())
    processed.append(session["session_key"])
save_state(processed)
```

Polling `status()` hourly is enough; there is no value in tighter loops,
because schedules only refresh every six hours anyway.

## Before publishing anything

`race.crosscheck()` validates a race across independent sources — sector
sums, lap counts, gap monotonicity, the `+N LAP` convention, on-track
passes against lead changes, and stint/pit consistency. Gate publication
on `publishable`; `mismatches` names what disagreed and `skipped` names
what could not be compared at all (a sprint has no `/overtakes` feed).

`race.quality_report()` is the wider gate, and the one to log. It embeds
the crosscheck verdict and adds what agreement alone cannot see:

```python
q = race.quality_report()
q["state"]                # provisional | settled | final | corrected
q["coverage"]["overall"]  # completeness of the fields the result is built on
q["missing"][:3]          # ['STR.lap_46.lap_duration', ...]
q["source_age_seconds"]   # how old the copy behind this answer is
q["revisions"]            # source rewrites seen for this session
q["publishable"]          # crosscheck AND settled AND complete enough
```

`state` is the field to branch on. `provisional` means the timing data is
still moving — hold. `corrected` means a row this installation had already
seen was rewritten, so anything published from the earlier copy needs a
correction notice.

Detail fields (sector times, compounds) are reported and warned about but
do not gate: out-laps legitimately carry no sector times, and in
qualifying that is most of the session.

## Sessions other than the race

```python
f1verse.sessions(2026, 12)                        # what that weekend had
f1verse.load_session(2026, 12, "Qualifying")      # → Qualifying
f1verse.load_session(2026, 12, "Sprint")          # → Race (it is one)
```

`load(year, round)` remains the race. Each kind returns the
classification it actually has — segment times and cut margins for
qualifying, a best-lap table for practice — rather than forcing all four
through a race-shaped formatter.

## Verification

```bash
pytest -q
```

Tests pin behaviour to a reference race. Run them after any change to
parsing, gap formatting or domain rules.
