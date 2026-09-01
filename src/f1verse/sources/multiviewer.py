# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Circuit geometry (MultiViewer public API).

Track outline, corner numbers/angles, marshal sectors and pit loss —
the pieces needed to draw a circuit map or explain where a lap was won.
Referenced by OpenF1 itself via each meeting's ``circuit_info_url``.
"""
from .. import http

BASE = "https://api.multiviewer.app/api/v1/circuits/"


def circuit(circuit_key: int, year: int) -> dict:
    # Layout metadata can be corrected while a season is under way. It is
    # stable enough to avoid repeat traffic in one preview, but not immutable
    # in the way completed lap telemetry is.
    return http.get_json(f"{BASE}{circuit_key}/{year}", ttl=http.TTL_SCHEDULE)
