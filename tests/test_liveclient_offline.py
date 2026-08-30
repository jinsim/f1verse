"""Wire framing, hub decoding and recordings — no network anywhere."""
import io
import struct

import pytest

from f1verse.sources.liveclient import (SEP, SessionTurnover, decode,
                                        frame_text, read_frame, replay)


def _server_frame(payload: bytes, opcode=0x1) -> bytes:
    """Servers send unmasked frames."""
    head = bytearray([0x80 | opcode])
    if len(payload) < 126:
        head.append(len(payload))
    else:
        head.append(126)
        head += struct.pack(">H", len(payload))
    return bytes(head) + payload


def test_client_frames_are_masked_and_round_trip():
    wire = frame_text("hello" * 100)
    assert wire[1] & 0x80                      # mask bit set
    op, body = read_frame(io.BytesIO(wire).read)
    assert op == 0x1 and body == b"hello" * 100


def test_fragmented_server_message_is_reassembled():
    part1 = bytes([0x01, 3]) + b"foo"          # FIN clear, text
    part2 = bytes([0x80, 3]) + b"bar"          # FIN set, continuation
    op, body = read_frame(io.BytesIO(part1 + part2).read)
    assert op == 0x1 and body == b"foobar"


def test_snapshot_arrives_as_our_completion():
    frame = ('{"type": 3, "invocationId": "abc", '
             '"result": {"TimingData": {}}}')
    items = list(decode(frame, "abc"))
    assert items == [("snapshot", {"TimingData": {}}, None)]
    assert list(decode(frame, "someone-else")) == []


def test_feed_frames_pass_and_housekeeping_is_skipped():
    feed = ('{"type": 1, "target": "feed", '
            '"arguments": ["TrackStatus", {"Status": "4"}, "t"]}')
    assert list(decode(feed, "x")) == [("TrackStatus", {"Status": "4"}, "t")]
    assert list(decode('{"type": 6}', "x")) == []       # ping
    assert list(decode("not json at all", "x")) == []   # skipping is recovery


def test_a_new_session_name_ends_the_connection():
    frame = ('{"type": 1, "target": "feed", "arguments": '
             '["SessionInfo", {"Name": "Race"}, "t"]}')
    with pytest.raises(SessionTurnover):
        list(decode(frame, "x"))


def test_replay_reads_stamped_and_bare_recordings(tmp_path):
    p = tmp_path / "mixed.log"
    p.write_text(f'1000\t{{"a": 1}}{SEP}{{"b": 2}}\n'
                 '{"c": 3}\n'                    # a stamp-less foreign line
                 f'2000\t{{"d": 4}}\n', encoding="utf-8")
    rows = replay(p)
    assert [t for t, _ in rows] == [1000, 1000, 1100, 2000]
    assert [f for _, f in rows] == ['{"a": 1}', '{"b": 2}',
                                    '{"c": 3}', '{"d": 4}']


def test_budget_is_enforced_per_host(monkeypatch):
    from f1verse import http
    monkeypatch.setitem(http._HOURLY_BUDGET, "example.test", 2)
    monkeypatch.setattr(http, "_request_log", {})
    http._spend("example.test")
    http._spend("example.test")
    with pytest.raises(http.BudgetExhausted):
        http._spend("example.test")
    http._spend("other.test")                   # budgets do not bleed over
