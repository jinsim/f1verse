"""Circuit profiles — geometry, layout facts and historic record in one call.

Answers the questions a race preview asks: what does this track look like,
how many corners, how costly is a pit stop here, who wins here, and does
pole convert?
"""
from ._json import jsonsafe
from .history import circuit_history
from .sources import multiviewer, openf1

# Jolpica circuit ids differ from OpenF1 short names for a handful of tracks.
_JOLPICA_ID = {
    "Zandvoort": "zandvoort", "Monza": "monza", "Spa-Francorchamps": "spa",
    "Silverstone": "silverstone", "Monaco": "monaco", "Suzuka": "suzuka",
    "Interlagos": "interlagos", "Yas Marina Circuit": "yas_marina",
    "Hungaroring": "hungaroring", "Red Bull Ring": "red_bull_ring",
    "Catalunya": "catalunya", "Baku": "baku", "Jeddah": "jeddah",
    "Sakhir": "bahrain", "Melbourne": "albert_park", "Shanghai": "shanghai",
    "Miami": "miami", "Montreal": "villeneuve", "Marina Bay": "marina_bay",
    "Austin": "americas", "Mexico City": "rodriguez", "Las Vegas": "vegas",
    "Losail": "losail", "Imola": "imola", "Madring": "madring",
}


def profile(year: int, rnd: int, history: bool = True) -> dict:
    """Circuit profile for a given round."""
    s = openf1.resolve_race(year, rnd)
    m = s["meeting"]
    geo = multiviewer.circuit(m["circuit_key"], year)
    corners = geo.get("corners", [])
    out = {
        "name": geo.get("circuitName") or m["circuit_short_name"],
        "official_name": m.get("meeting_official_name"),
        "country": m.get("country_name"),
        "location": m.get("location"),
        "type": m.get("circuit_type"),
        "utc_offset": m.get("gmt_offset"),
        "corners": len(corners),
        "corner_detail": [{"number": c.get("number"), "angle": c.get("angle"),
                           "distance": c.get("length")} for c in corners],
        "marshal_sectors": len(geo.get("marshalSectors", [])),
        # seconds lost in the pit lane, split by track state — the number an
        # undercut calculation needs, and the reason a VSC stop is "cheap"
        "pit_loss_s": {k: float(v) for k, v in
                       (geo.get("pitLoss") or {}).items()},
        "outline": {"x": geo.get("x", []), "y": geo.get("y", []),
                    "rotation": geo.get("rotation")},
        "reference_lap": (lambda c: {
            "time_s": c.get("lapTime"), "session": c.get("session"),
            "driver_number": c.get("driverNumber")} if c else None)(
                geo.get("candidateLap")),
    }
    if history:
        jid = _JOLPICA_ID.get(out["name"])
        if jid:
            out["history"] = circuit_history(jid)
    return jsonsafe(out)
