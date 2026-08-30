"""Circuit geometry (MultiViewer public API).

Track outline, corner numbers/angles, marshal sectors and pit loss —
the pieces needed to draw a circuit map or explain where a lap was won.
Referenced by OpenF1 itself via each meeting's ``circuit_info_url``.
"""
from .. import http

BASE = "https://api.multiviewer.app/api/v1/circuits/"


def circuit(circuit_key: int, year: int) -> dict:
    return http.get_json(f"{BASE}{circuit_key}/{year}")
