# Operating f1verse

How to run this continuously without hammering the upstream APIs or
publishing half-finished data.

## Caching is by mutability, not blanket

Completed sessions never change; schedules do. A calendar cached for a
season would hide a cancelled round for the rest of the year, so cache
policy is chosen per endpoint class:

| Data | TTL | Constant |
|---|---|---|
| Completed-session laps, results, stints, pits | forever | `TTL_FOREVER` |
| Schedules — sessions, meetings, season index | 6 hours | `TTL_SCHEDULE` |
| Championship standings | 1 hour | `TTL_STANDINGS` |
| In-progress session data | 1 minute | `TTL_LIVE` |

Callers do not choose: `sources/openf1.py` and `sources/jolpica.py` pick
the policy from the endpoint. If a refresh fails but a stale entry exists,
the stale copy is served — an hour-old schedule beats no schedule.

```python
f1verse.enable_cache("path/to/cache")   # default: ~/.cache/f1verse
f1verse.cache_info()                    # {'entries': 107, 'bytes': 2837844}
f1verse.clear_cache(older_than=30*86400)
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
on `publishable`; the `mismatches` list names what disagreed.

## Verification

```bash
pytest -q
```

Tests pin behaviour to a reference race. Run them after any change to
parsing, gap formatting or domain rules.
