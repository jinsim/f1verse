"""Lap reconstruction from the raw patch stream, offline."""
from f1verse._clock import clock_seconds, lap_seconds, wall_time
from f1verse.sources.timing import laps_from_stream


def line(**kw):
    return {"Lines": {"44": kw}}


def test_clock_parsing_tolerates_the_feed_shapes():
    assert clock_seconds("01:02:03.500") == 3723.5
    assert clock_seconds("02:03.5") == 123.5
    assert clock_seconds("garbage") is None
    assert lap_seconds("1:23.456") == 83.456
    assert lap_seconds("28.901") == 28.901
    assert lap_seconds("") is None
    ts = wall_time("2026-06-01T14:00:00.1234567")   # seven digits, no Z
    assert ts is not None and ts.microsecond == 123456
    assert wall_time("2026-06-01T14:00:00Z").tzinfo is not None


def test_a_slow_sector_message_lands_on_the_lap_that_ran_it():
    records = [
        (10.0, line(NumberOfLaps=1)),
        (100.0, line(NumberOfLaps=2)),                       # lap 2 begins
        (101.5, line(Sectors={"2": {"Value": "31.204"}})),   # late lap-1 news
        (140.0, line(Sectors={"0": {"Value": "29.000"}})),   # honest lap-2 news
    ]
    laps = laps_from_stream(records)["44"]
    assert laps[0]["sectors_s"][2] == 31.204
    assert laps[1]["sectors_s"][0] == 29.0


def test_the_start_line_speed_trap_belongs_to_the_new_lap():
    records = [
        (10.0, line(NumberOfLaps=1)),
        (100.0, line(NumberOfLaps=2)),
        (101.0, line(Speeds={"ST": {"Value": "312"}})),   # inside the window
        (101.0, line(Speeds={"FL": {"Value": "280"}})),   # also inside it
    ]
    laps = laps_from_stream(records)["44"]
    assert laps[1]["speeds_kmh"]["ST"] == 312     # new lap keeps the trap
    assert laps[0]["speeds_kmh"]["FL"] == 280     # the finish line was lap 1's


def test_blank_lap_time_is_filled_from_sectors_but_unknown_is_not():
    base = {"Sectors": {"0": {"Value": "28.0"}, "1": {"Value": "30.0"},
                        "2": {"Value": "25.456"}}}
    records = [
        (10.0, line(NumberOfLaps=1)),
        (50.0, line(**base)),
        (95.0, line(LastLapTime={"Value": ""})),   # the feed says: no value
        (100.0, line(NumberOfLaps=2)),
        (150.0, line(Sectors={"0": {"Value": "28.5"}})),
    ]
    laps = laps_from_stream(records)["44"]
    assert laps[0]["time_s"] == 83.456
    assert laps[0]["filled_from_sectors"] is True
    assert laps[1]["time_s"] is None               # unknown stays unknown
    assert laps[1]["filled_from_sectors"] is False


def test_a_between_runs_artefact_is_not_a_lap_time():
    records = [
        (10.0, line(NumberOfLaps=1)),
        (400.0, line(LastLapTime={"Value": "6:12.000"})),   # garage visit
        (410.0, line(LastLapTime={"Value": "1:19.500"})),
    ]
    laps = laps_from_stream(records)["44"]
    assert laps[0]["time_s"] == 79.5


def test_ghost_laps_are_trimmed_and_renumbered():
    records = [
        (10.0, line(NumberOfLaps=1)),           # never gets any data
        (100.0, line(NumberOfLaps=2)),
        (150.0, line(LastLapTime={"Value": "1:20.000"},
                     Sectors={"1": {"Value": "30.0"}})),
        (160.0, line(NumberOfLaps=3)),          # trailing ghost
    ]
    laps = laps_from_stream(records)["44"]
    assert len(laps) == 1 and laps[0]["lap"] == 1
    assert laps[0]["time_s"] == 80.0


def test_lap_end_takes_the_earliest_witness():
    records = [
        (10.0, line(NumberOfLaps=1)),
        (40.0, line(Sectors={"1": {"Value": "30.0"}})),
        # sector 3's own message is 4s late; counting forward from the
        # sector-2 arrival says the lap ended at 40 + 25 = 65
        (69.0, line(Sectors={"2": {"Value": "25.0"}})),
    ]
    laps = laps_from_stream(records)["44"]
    assert laps[0]["ended"] == 65.0


def test_pit_calls_land_where_they_happened():
    records = [
        (10.0, line(NumberOfLaps=1)),
        (80.0, line(InPit=True)),
        (100.0, line(NumberOfLaps=2)),
        (108.0, line(InPit=False, Sectors={"0": {"Value": "40.0"}})),
    ]
    laps = laps_from_stream(records)["44"]
    assert laps[0]["pit_in"] == 80.0
    assert laps[1]["pit_out"] == 108.0
