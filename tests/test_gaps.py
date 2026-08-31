# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Gap formatting rules, without touching the network."""
from datetime import timedelta

import pytest

from f1verse.gaps import format_gap, format_seconds


def test_winner_is_labelled_not_timed():
    assert format_gap("Finished", timedelta(seconds=7484), position=1) == "WINNER"


@pytest.mark.parametrize("seconds,expected", [
    (11.536, "+11.536s"),
    (79.915, "+1:19.915"),
    (0.881, "+0.881s"),      # milliseconds are never rounded away
])
def test_interval_formatting(seconds, expected):
    assert format_seconds(seconds) == expected


def test_lapped_cars_never_show_an_interval():
    # the raw value is deliberately smaller than a lead-lap car's gap
    assert format_gap("Lapped", timedelta(seconds=36.049), position=8) == "+1 LAP"
    assert format_gap("Lapped", None, position=15, laps_down=2) == "+2 LAPS"


@pytest.mark.parametrize("status,expected", [
    ("Retired", "DNF"),
    ("Accident", "DNF"),
    ("Disqualified", "DSQ"),
])
def test_non_finishers(status, expected):
    assert format_gap(status, None, position=None) == expected
