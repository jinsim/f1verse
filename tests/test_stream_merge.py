# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Live-timing patch semantics and compressed channels, offline."""
import base64
import zlib

from f1verse.gaps import reconcile
from f1verse.sources.livetiming import deepmerge, unpack_z


def test_list_patches_arrive_as_indexed_dicts():
    base = {"Sectors": [{"Value": "30.1"}, {"Value": "28.9"}]}
    patched = deepmerge(base, {"Sectors": {"1": {"Value": "28.7"}}})
    assert patched["Sectors"][1]["Value"] == "28.7"
    assert patched["Sectors"][0]["Value"] == "30.1"


def test_index_past_the_end_appends():
    base = {"Messages": [{"n": 1}]}
    patched = deepmerge(base, {"Messages": {"5": {"n": 2}}})
    assert [m["n"] for m in patched["Messages"]] == [1, 2]


def test_non_index_keys_replace_the_list():
    assert deepmerge([1, 2], {"Value": 3}) == {"Value": 3}


def test_two_lists_never_concatenate():
    assert deepmerge({"a": [1, 2]}, {"a": [3]}) == {"a": [3]}


def test_unpack_z_round_trip():
    body = b'{"Entries": [{"Utc": "2026-06-01T14:00:00Z"}]}'
    packer = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    wire = base64.b64encode(packer.compress(body) + packer.flush()).decode()
    assert unpack_z(wire)["Entries"][0]["Utc"].startswith("2026")
    # streams sometimes hand the payload over still wearing its quotes
    assert unpack_z(f'"{wire}"')["Entries"][0]["Utc"].startswith("2026")


def test_reconcile_prefers_official_and_calibrates_the_rest():
    rows = [
        {"lap": 1, "official": 2.0, "derived": 1.5},
        {"lap": 2, "official": 3.1, "derived": 2.6},
        {"lap": 3, "official": None, "derived": 4.0},
        {"lap": 4, "official": None, "derived": None},
    ]
    out = reconcile(rows)
    assert out[0] == {"lap": 1, "gap_s": 2.0, "source": "official"}
    # both anchors agree the derived series sits 0.5 s low
    assert out[2] == {"lap": 3, "gap_s": 4.5, "source": "calibrated"}
    assert out[3]["gap_s"] is None and out[3]["source"] is None


def test_reconcile_without_anchors_is_honest_about_it():
    out = reconcile([{"lap": 1, "official": None, "derived": -0.02}])
    assert out[0]["source"] == "derived"
    # a derived gap a whisker below zero is noise, not a faster car
    assert out[0]["gap_s"] == 0.0
