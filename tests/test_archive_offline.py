# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Era coverage and lap-order maths, without touching the network."""
import pytest

from f1verse.archive import LAPS_FROM, NATIVE_FROM, PITS_FROM, coverage


def test_coverage_is_honest_about_each_era():
    old = coverage(1994)
    assert old["results"] and not old["lap_times"] and not old["pit_stops"]
    assert old["note"] == "results and standings only"

    mid = coverage(2005)
    assert mid["lap_times"] and mid["running_order"] and not mid["pit_stops"]

    late = coverage(2015)
    assert late["pit_stops"] and not late["stints"] and not late["telemetry"]

    now = coverage(2025)
    assert now["stints"] and now["telemetry"] and now["weather"]
    assert now["note"] == "full live-timing coverage"


@pytest.mark.parametrize("year,field", [
    (LAPS_FROM, "lap_times"), (PITS_FROM, "pit_stops"), (NATIVE_FROM, "stints"),
])
def test_boundaries_are_inclusive(year, field):
    # the first season of an era must already have it, the one before not
    assert coverage(year)[field] is True
    assert coverage(year - 1)[field] is False


def test_a_missing_field_is_never_a_zero():
    # every era answers the same question set; absence is stated, not implied
    assert set(coverage(1994)) == set(coverage(2025))
