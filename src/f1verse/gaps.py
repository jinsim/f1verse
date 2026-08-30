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
