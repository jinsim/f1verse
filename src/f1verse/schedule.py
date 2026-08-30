"""Season calendar and run scheduling — when should a pipeline wake up?

An automated pipeline needs to answer three questions without a human:
is a session finished, is the data settled enough to publish, and when is
the next thing worth waking up for. Timing data is typically complete a
short while after the chequered flag, so a pipeline that fires at the
finish will publish half a race.
"""
from datetime import datetime, timedelta, timezone

from ._json import jsonsafe
from .sources import openf1

SETTLE_MINUTES = 45   # how long after a session ends before data is stable


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def season(year: int, *, kind: str | None = None) -> list:
    """All sessions of a season, chronologically, with round numbers.

    Cancelled meetings are dropped, so round numbers stay meaningful —
    the same filter :func:`f1verse.load` uses.
    """
    meetings = sorted(openf1.get("meetings", year=year),
                      key=lambda m: m["date_start"])
    gps = [m for m in meetings if "test" not in m["meeting_name"].lower()
           and not m.get("is_cancelled")]
    # sessions rows carry no meeting name — join it from meetings
    meta = {m["meeting_key"]: (i + 1, m["meeting_name"])
            for i, m in enumerate(gps)}
    out = []
    for s in sorted(openf1.get("sessions", year=year),
                    key=lambda s: s["date_start"]):
        rnd, name = meta.get(s["meeting_key"], (None, None))
        if rnd is None or (kind and s["session_name"] != kind):
            continue
        out.append({"round": rnd, "meeting": name,
                    "location": s.get("location"),
                    "session": s["session_name"],
                    "session_key": s["session_key"],
                    "start": s["date_start"], "end": s["date_end"],
                    "utc_offset": s.get("gmt_offset")})
    return jsonsafe(out)


def status(year: int, *, now: datetime | None = None) -> dict:
    """Where the season currently stands, and what to do next.

    Returns ``ready`` — sessions finished and settled but not yet known to
    be processed — plus the next session and how long until it is due.
    """
    now = now or datetime.now(timezone.utc)
    settle = timedelta(minutes=SETTLE_MINUTES)
    done, ready, upcoming = [], [], []
    for s in season(year):
        end = _dt(s["end"])
        if end + settle <= now:
            done.append(s)
            ready.append(s)
        elif end <= now:
            pass                      # finished but still settling
        else:
            upcoming.append(s)
    nxt = upcoming[0] if upcoming else None
    return jsonsafe({
        "now": now.isoformat(),
        "completed": len(done),
        "latest_race": next((s for s in reversed(done)
                             if s["session"] == "Race"), None),
        "ready": ready[-3:],
        "next": nxt,
        "next_in_hours": (round((_dt(nxt["start"]) - now).total_seconds() / 3600, 1)
                          if nxt else None),
        "settle_minutes": SETTLE_MINUTES,
    })


def due(year: int, processed: list | None = None,
        *, kind: str = "Race", now: datetime | None = None) -> list:
    """Sessions that are finished, settled, and not in *processed*.

    ``processed`` is a list of session keys the caller has already handled
    — a pipeline keeps that list and passes it back each run, so nothing is
    published twice and nothing is missed after downtime.
    """
    now = now or datetime.now(timezone.utc)
    seen = set(processed or ())
    settle = timedelta(minutes=SETTLE_MINUTES)
    return jsonsafe([s for s in season(year, kind=kind)
                     if s["session_key"] not in seen
                     and _dt(s["end"]) + settle <= now])
