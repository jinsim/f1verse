# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Wire-format clocks, parsed without a dependency.

The timing feeds are inconsistent about time in three separate ways: a
stream clock that counts from session start, wall-clock timestamps whose
fractional part runs anywhere from one to seven digits (and usually
arrives without a trailing ``Z``), and lap times written the way a
broadcaster prints them. ``datetime.fromisoformat`` on Python 3.9 accepts
none of the awkward cases, so this module owns the parsing — every module
that touches a feed value routes through here rather than growing its own
regex.
"""
from __future__ import annotations

from datetime import datetime, timezone


def clock_seconds(text: str) -> float | None:
    """A session-clock reading — ``"01:23:45.678"`` — as plain seconds.

    Tolerates a missing hours field and any number of fractional digits,
    because the feeds use all of those shapes. Returns ``None`` rather
    than raising: a malformed clock is a data problem to report, not a
    crash.
    """
    parts = (text or "").strip().split(":")
    if not 2 <= len(parts) <= 3:
        return None
    try:
        fields = [float(p) for p in parts]
    except ValueError:
        return None
    if len(fields) == 2:
        fields.insert(0, 0.0)
    h, m, s = fields
    return h * 3600 + m * 60 + s


def lap_seconds(text: str) -> float | None:
    """A printed lap or sector time — ``"1:23.456"`` or ``"28.901"`` —
    as seconds. Empty strings and dashes come back as ``None``."""
    text = (text or "").strip()
    if not text or set(text) <= {"-", "."}:
        return None
    try:
        if ":" in text:
            m, s = text.split(":", 1)
            return int(m) * 60 + float(s)
        return float(text)
    except ValueError:
        return None


def wall_time(text: str) -> datetime | None:
    """A feed timestamp — ISO-shaped, fraction of any width, ``Z``
    optional — as an aware UTC datetime.

    The official streams emit seven fractional digits, which no stdlib
    parser accepts directly; the fraction is cut (never rounded) to
    microseconds first. A timestamp with no zone designator is UTC — the
    feeds never speak local time, whatever the session's circuit.
    """
    text = (text or "").strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = "".join(c for c in frac if c.isdigit())
        text = f"{head}.{frac[:6].ljust(6, '0')}" if frac else head
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
