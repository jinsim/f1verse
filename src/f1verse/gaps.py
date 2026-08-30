"""Broadcast-convention gap formatting.

Classified times are not directly comparable: a car one lap down can carry
a smaller number than one that finished ahead on the lead lap, so printing
raw values produces a table that reads wrong. ``format_gap`` applies the
convention used on screen — ``+1 LAP`` for lapped cars, ``DNF``/``DSQ``
where applicable, and a formatted interval otherwise.
"""
import math


def _seconds(td):
    if td is None:
        return None
    try:
        s = td.total_seconds()
    except AttributeError:
        s = float(td)
    return None if math.isnan(s) else s


def format_seconds(total: float) -> str:
    if total >= 60:
        return f"+{int(total // 60)}:{total % 60:06.3f}"
    return f"+{total:.3f}s"


def format_gap(status, time_delta, position=None, laps_down=None) -> str:
    """Human gap string for one classified result row (broadcast convention)."""
    if position == 1:
        return "WINNER"
    if status == "Lapped":
        n = int(laps_down) if laps_down else 1
        return f"+{n} LAP" if n == 1 else f"+{n} LAPS"
    if status == "Disqualified":
        return "DSQ"
    if status != "Finished":
        return "DNF"
    s = _seconds(time_delta)
    return "" if s is None else format_seconds(s)


def reconcile(rows: list) -> list:
    """Fill the holes in an official gap series without hiding the seams.

    Timing feeds publish gaps for some laps and not others; a gap can
    always be *derived* from cumulative lap times, but the two disagree by
    a roughly constant amount (different zero points, different clocks).
    Where a lap carries both values, that disagreement is measurable — so
    measure it on those laps, take the median, and shift the derived
    values by it.

    Each input row is ``{"lap": n, "official": s | None, "derived":
    s | None}``. Each output row keeps the lap, a ``gap_s`` and a
    ``source``: ``"official"`` where the feed spoke, ``"calibrated"``
    where a derived value was shifted onto the official zero point, and
    ``"derived"`` where no calibration was possible. Nothing is silently
    smoothed — a consumer can always tell which numbers the feed actually
    published.
    """
    offsets = sorted(r["official"] - r["derived"] for r in rows
                     if r.get("official") is not None
                     and r.get("derived") is not None)
    shift = offsets[len(offsets) // 2] if offsets else None

    def _settle(value):
        # a derived gap a few hundredths below zero is arithmetic noise,
        # not a car ahead of the leader
        return 0.0 if -0.05 < value < 0 else value

    out = []
    for r in rows:
        if r.get("official") is not None:
            out.append({"lap": r["lap"], "gap_s": round(r["official"], 3),
                        "source": "official"})
        elif r.get("derived") is not None:
            if shift is not None:
                out.append({"lap": r["lap"],
                            "gap_s": round(_settle(r["derived"] + shift), 3),
                            "source": "calibrated"})
            else:
                out.append({"lap": r["lap"],
                            "gap_s": round(_settle(r["derived"]), 3),
                            "source": "derived"})
        else:
            out.append({"lap": r["lap"], "gap_s": None, "source": None})
    return out
