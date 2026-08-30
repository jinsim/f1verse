"""Track conditions through a session.

Weather is sampled about once a minute: air and track temperature,
humidity, pressure, wind and a rainfall flag. Track temperature in
particular explains tyre behaviour that lap times alone do not.
"""
from ._json import jsonsafe
from .sources import openf1


def readings(race) -> list:
    """Every weather sample of the session, chronologically."""
    rows = sorted(openf1.get("weather", session_key=race.session_key),
                  key=lambda r: r["date"])
    return jsonsafe([{
        "date": r["date"], "air_c": r.get("air_temperature"),
        "track_c": r.get("track_temperature"), "humidity": r.get("humidity"),
        "pressure": r.get("pressure"), "wind_speed": r.get("wind_speed"),
        "wind_direction": r.get("wind_direction"),
        "rain": bool(r.get("rainfall")),
    } for r in rows])


def summary(race) -> dict:
    """Ranges and whether it rained — the line a race report needs."""
    rows = readings(race)
    if not rows:
        return {}
    def rng(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return {"min": min(vals), "max": max(vals)} if vals else None
    return jsonsafe({
        "samples": len(rows),
        "air_c": rng("air_c"), "track_c": rng("track_c"),
        "humidity": rng("humidity"), "wind_speed": rng("wind_speed"),
        "rain": any(r["rain"] for r in rows),
        "rain_samples": sum(r["rain"] for r in rows),
    })
