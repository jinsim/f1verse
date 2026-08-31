"""Running order, churn and battle detection, on a fixed synthetic race."""
from f1verse.race import Race


class _Stub(Race):
    """A three-car race with a known story: C passes B on lap 3, and A and
    B run together the whole way."""

    def __init__(self):
        base = "2026-06-01T14:0{m}:{s:02d}+00:00"
        self.drivers = {1: {}, 2: {}, 3: {}}
        self._abbr = {1: "AAA", 2: "BBB", 3: "CCC"}
        self.laps = []
        # cumulative start times: A always first, C starts last but is
        # quicker and takes second place on lap 3
        starts = {1: [0, 90, 180, 270], 2: [1, 91, 182, 273],
                  3: [2, 92, 181, 271]}
        # A and B lap within a few tenths of each other all race; C is
        # quicker and gets past B on lap 3
        pace = {1: 90.0, 2: 90.3, 3: 90.0}
        for num, ts in starts.items():
            for i, t in enumerate(ts):
                self.laps.append({
                    "driver_number": num, "lap_number": i + 1,
                    "date_start": base.format(m=t // 60, s=t % 60),
                    "lap_duration": pace[num]})

    def abbr(self, num):
        return self._abbr[num]


def test_running_order_reads_the_lap_feed():
    r = _Stub()
    order = r._order()
    assert order[1] == ["AAA", "BBB", "CCC"]
    assert order[3] == ["AAA", "CCC", "BBB"]      # the pass shows up
    assert r.running_order()["3"] == ["AAA", "CCC", "BBB"]   # keys stringify


def test_position_changes_name_the_mover():
    changes = {c["lap"]: c for c in _Stub().position_changes()}
    assert changes[2]["moves"] == 0                # nothing happened
    assert changes[3]["moves"] == 2                # two cars swapped
    assert changes[3]["biggest"] == {"abbr": "CCC", "gained": 1,
                                     "from": 3, "to": 2}


def test_battles_need_proximity_and_persistence():
    r = _Stub()
    pairs = {(b["ahead"], b["behind"]): b for b in r.battles(min_laps=2)}
    assert ("AAA", "BBB") in pairs        # together until C split them up
    assert pairs[("AAA", "BBB")]["closest"] <= 1.5
    assert pairs[("AAA", "BBB")]["laps"] == 2      # laps 1-2, then C is by
    assert ("AAA", "CCC") in pairs                 # laps 3-4
    # an impossible tolerance finds nothing rather than erroring
    assert r.battles(within_s=0.0001) == []
