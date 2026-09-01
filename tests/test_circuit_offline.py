# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Circuit-shape facts, without calling a map provider."""
import json

from f1verse import circuit
from f1verse.circuit import layout_diagnostics


_TRACE = {
    # An eight-point square, ordered counterclockwise in source coordinates.
    "x": [0, 1, 2, 2, 2, 1, 0, 0],
    "y": [0, 0, 0, 1, 2, 2, 2, 1],
    "corners": [
        {"number": 1, "length": 2, "trackPosition": {"x": 2, "y": 0}},
        {"number": 2, "length": 4, "trackPosition": {"x": 2, "y": 2}},
        {"number": 3, "length": 6, "trackPosition": {"x": 0, "y": 2}},
        {"number": 4, "length": 8, "trackPosition": {"x": 0, "y": 0}},
    ],
    "miniSectorsIndexes": [2, 4, 6],
    "marshalSectors": [{"number": 2, "trackPosition": {"x": 2, "y": 2}}],
}


def test_layout_diagnostics_reports_shape_without_claiming_metres():
    report = layout_diagnostics(_TRACE)
    assert json.dumps(report)
    assert report["available"] is True
    assert report["point_count"] == 8
    assert report["coordinate_path_length"] == 8.0
    assert report["coordinate_units"] == "map-source units (not surveyed metres)"
    assert report["trace_winding"] == "counterclockwise"
    assert report["bounds"]["aspect_ratio"] == 1.0
    assert report["bounds"]["trace_to_bounds_fill"] == 1.0
    assert report["coverage"]["elevation"]["available"] is False
    assert report["coverage"]["drs_zones"]["available"] is False
    assert report["coverage"]["track_width"]["available"] is False


def test_corner_positions_and_sector_intervals_follow_the_trace():
    report = layout_diagnostics(_TRACE)
    corners = {row["number"]: row for row in report["corners"]}
    assert corners[1]["progress_pct"] == 25.0
    assert corners[1]["local_deflection_deg"] == 90.0
    assert all(row["run_from_previous_pct"] == 25.0
               for row in report["corners"])
    assert [row["lap_pct"] for row in report["mini_sectors"]] == [25.0] * 4
    assert report["marshal_sector_markers"] == [{"number": 2, "progress_pct": 50.0}]


def test_layout_diagnostics_rejects_a_non_trace_cleanly():
    report = layout_diagnostics({"x": [0, "bad"], "y": [0, 1]})
    assert report == {"available": False,
                      "reason": "fewer than three finite trace points",
                      "point_count": 1}


def test_layout_diagnostics_ignores_malformed_optional_markers():
    report = layout_diagnostics({**_TRACE, "corners": [None, *_TRACE["corners"]],
                                 "miniSectorsIndexes": ["2", None, "no"],
                                 "marshalSectors": ["no", *_TRACE["marshalSectors"]]})
    assert report["mini_sectors"][0]["to_point"] == 2
    assert len(report["corners"]) == 4
    assert report["marshal_sector_markers"][0]["number"] == 2


def test_circuit_directory_is_a_runtime_history_index(monkeypatch):
    monkeypatch.setattr(circuit.jolpica, "circuits", lambda: [
        {"circuitId": "zeta", "circuitName": "Zeta", "Location":
         {"locality": "Last", "country": "Zed", "lat": "-12.3", "long": "45.6"}},
        {"circuitId": "alpha", "circuitName": "Alpha", "Location":
         {"locality": "First", "country": "Aland", "lat": "bad", "long": None}},
    ])
    report = circuit.directory()
    assert json.dumps(report)
    assert [row["id"] for row in report["circuits"]] == ["alpha", "zeta"]
    assert report["circuits"][0]["location"]["latitude"] is None
    assert report["circuits"][1]["location"]["longitude"] == 45.6
    assert "specific season/layout" in report["coverage"]["geometry"]
