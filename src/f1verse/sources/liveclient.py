# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Live timing over the wire — standard library only.

The official feed speaks the modern SignalR hub protocol over a
WebSocket, and getting connected takes three undocumented courtesies:
the load balancer hands out an affinity cookie only to a pre-flight
``OPTIONS`` request and rejects sockets that arrive without it; the
service expects the user agent of the official application; and a
subscription without an invocation id is accepted silently and never
answered. All three live here so no caller has to rediscover them.

Frames on the socket are JSON documents separated by an ASCII record
separator. The snapshot of the whole session state arrives as the
*completion* of our subscribe call (matched by that invocation id);
everything after is a ``feed`` invocation carrying ``(topic, patch,
timestamp)``. The hub also sends pings and other housekeeping — a frame
that is not a feed is skipped, never an error, because the protocol adds
frame types without notice.

**Recording.** :func:`record` writes every raw frame with a millisecond
arrival stamp, one per line, so a session can be replayed later at true
speed — the stamp is the difference between an archive and a screenshot.
:func:`replay` also accepts stamp-less lines (some third-party recordings
have no timing) and paces those uniformly.

Nothing here is redistributed; recordings are local working data.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import socket
import ssl
import struct
import time
import urllib.parse
import urllib.request
import uuid

HOST = "livetiming.formula1.com"
NEGOTIATE = f"https://{HOST}/signalrcore/negotiate?negotiateVersion=1"
SEP = "\x1e"
_HEADERS = {"User-Agent": "BestHTTP", "Accept-Encoding": "gzip, identity"}

TOPICS = [
    "Heartbeat", "AudioStreams", "DriverList", "ExtrapolatedClock",
    "RaceControlMessages", "SessionInfo", "SessionStatus", "TeamRadio",
    "TimingAppData", "TimingStats", "TrackStatus", "WeatherData",
    "Position.z", "CarData.z", "ContentStreams", "SessionData",
    "TimingData", "TopThree", "RcmSeries", "LapCount",
]


class SessionTurnover(Exception):
    """The feed switched to a different session; the connection is done."""


# --- WebSocket framing (client side, RFC 6455 subset) -------------------

def frame_text(payload: str) -> bytes:
    """One masked client text frame. Clients must mask; servers must not."""
    data = payload.encode("utf-8")
    head = bytearray([0x81])
    n = len(data)
    if n < 126:
        head.append(0x80 | n)
    elif n < 1 << 16:
        head.append(0x80 | 126)
        head += struct.pack(">H", n)
    else:
        head.append(0x80 | 127)
        head += struct.pack(">Q", n)
    mask = os.urandom(4)
    head += mask
    return bytes(head) + bytes(b ^ mask[i % 4] for i, b in enumerate(data))


def read_frame(read) -> tuple:
    """``(opcode, payload_bytes)`` from a ``read(n) -> bytes`` callable.

    Continuation frames are stitched back together before returning, so
    callers only ever see whole messages.
    """
    opcode, parts = None, []
    while True:
        b1, b2 = read(1)[0], read(1)[0]
        fin, op = b1 & 0x80, b1 & 0x0F
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", read(8))[0]
        mask = read(4) if b2 & 0x80 else None
        data = b""
        while len(data) < n:
            chunk = read(n - len(data))
            if not chunk:
                raise ConnectionError("socket closed mid-frame")
            data += chunk
        if mask:
            data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        if op != 0:
            opcode = op
        parts.append(data)
        if fin:
            return opcode, b"".join(parts)


def _accept_key(nonce: str) -> str:
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    return base64.b64encode(
        hashlib.sha1((nonce + magic).encode()).digest()).decode()


# --- connection ---------------------------------------------------------

def negotiate() -> tuple:
    """``(connection_token, cookie_header)`` — the pre-flight dance."""
    probe = urllib.request.Request(NEGOTIATE, method="OPTIONS",
                                   headers=dict(_HEADERS))
    cookie = ""
    with urllib.request.urlopen(probe, timeout=30) as r:
        for part in r.headers.get_all("Set-Cookie") or []:
            if part.startswith("AWSALBCORS="):
                cookie = part.split(";", 1)[0]
    post = urllib.request.Request(
        NEGOTIATE, method="POST", data=b"",
        headers={**_HEADERS, "Cookie": cookie})
    with urllib.request.urlopen(post, timeout=30) as r:
        token = json.loads(r.read().decode("utf-8"))["connectionToken"]
    return token, cookie


class LiveFeed:
    """One connection's worth of the live stream.

    Iterate :meth:`frames` for raw frame strings (what a recorder wants)
    or :meth:`messages` for decoded ``(topic, patch, timestamp)`` tuples
    plus one initial ``("snapshot", state, None)``. When the feed
    announces a different session, iteration ends with
    :class:`SessionTurnover` — reconnecting is a policy decision that
    belongs to the caller, and :func:`run` implements the standard one.
    """

    def __init__(self, topics=None):
        self.topics = list(topics or TOPICS)
        self._sock = None

    def connect(self) -> None:
        token, cookie = negotiate()
        nonce = base64.b64encode(os.urandom(16)).decode()
        raw = socket.create_connection((HOST, 443), timeout=60)
        self._sock = ssl.create_default_context().wrap_socket(
            raw, server_hostname=HOST)
        path = "/signalrcore?" + urllib.parse.urlencode({"id": token})
        request = (
            f"GET {path} HTTP/1.1\r\nHost: {HOST}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {nonce}\r\nSec-WebSocket-Version: 13\r\n"
            f"User-Agent: BestHTTP\r\nAccept-Encoding: gzip, identity\r\n"
            f"Cookie: {cookie}\r\n\r\n")
        self._sock.sendall(request.encode())
        reply = b""
        while b"\r\n\r\n" not in reply:
            reply += self._sock.recv(4096)
        head = reply.split(b"\r\n\r\n", 1)[0].decode("latin-1")
        status = head.split("\r\n")[0]
        if " 101 " not in f"{status} ":
            raise ConnectionError(f"upgrade refused: {status}")
        accept = next((l.split(":", 1)[1].strip() for l in head.split("\r\n")
                       if l.lower().startswith("sec-websocket-accept:")), "")
        if accept != _accept_key(nonce):
            raise ConnectionError("upgrade handshake failed verification")
        self._send(json.dumps({"protocol": "json", "version": 1}) + SEP)
        first = json.loads(self._next_text().split(SEP)[0])
        if first.get("error"):
            raise ConnectionError(f"handshake refused: {first['error']}")
        self._invocation = str(uuid.uuid4())
        self._send(json.dumps({
            "type": 1, "invocationId": self._invocation,
            "target": "Subscribe", "arguments": [self.topics]}) + SEP)

    def _send(self, text: str) -> None:
        self._sock.sendall(frame_text(text))

    def _next_text(self) -> str:
        while True:
            op, data = read_frame(self._sock.recv)
            if op == 0x9:                       # ping — answer and move on
                pong = frame_text("")
                self._sock.sendall(bytes([0x8A]) + pong[1:])
            elif op == 0x8:
                raise ConnectionError("server closed the socket")
            elif op == 0x1:
                return data.decode("utf-8")

    def frames(self):
        """Raw frame strings, one hub document at a time."""
        buffer = ""
        while True:
            buffer += self._next_text()
            while SEP in buffer:
                frame, buffer = buffer.split(SEP, 1)
                if frame:
                    yield frame

    def messages(self):
        for frame in self.frames():
            for item in decode(frame, self._invocation):
                yield item

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None


def decode(frame: str, invocation_id: str = ""):
    """Hub frames → ``(topic, data, timestamp)`` tuples.

    The subscribe completion becomes ``("snapshot", state, None)``;
    a ``feed`` invocation passes through; anything else — pings, other
    completions, frame types added since — yields nothing. Malformed
    frames also yield nothing: on a live wire, skipping is recovery.
    """
    try:
        doc = json.loads(frame)
    except (json.JSONDecodeError, TypeError):
        return
    kind = doc.get("type")
    if kind == 3 and doc.get("invocationId") == invocation_id:
        yield ("snapshot", doc.get("result") or {}, None)
    elif kind == 1 and doc.get("target") == "feed":
        args = doc.get("arguments") or []
        if len(args) >= 2:
            topic, data = args[0], args[1]
            stamp = args[2] if len(args) > 2 else None
            if topic == "SessionInfo" and isinstance(data, dict) \
                    and "Name" in data:
                raise SessionTurnover(data.get("Name"))
            yield (topic, data, stamp)


# --- the always-on recorder --------------------------------------------

def record(path, feed: LiveFeed | None = None) -> None:
    """Append every raw frame to ``path`` as ``<ms>\\t<frame>`` lines.

    The millisecond stamp is the local arrival time; it is what lets a
    replay run at true speed instead of a uniform trickle. The file is
    flushed per line — a crash loses at most the frame in flight. Ends by
    raising :class:`SessionTurnover` when the session changes, so a
    supervisor can rotate to a new file and reconnect.
    """
    feed = feed or LiveFeed()
    if feed._sock is None:
        feed.connect()
    with open(path, "a", encoding="utf-8") as fh:
        for frame in feed.frames():
            fh.write(f"{int(time.time() * 1000)}\t{frame}\n")
            fh.flush()
            for _ in decode(frame, feed._invocation):
                pass  # decoding here only to let SessionTurnover surface


def replay(path) -> list:
    """A recording → ``[(ms, frame), ...]``.

    Reads our stamped format, and also bare-frame recordings made by
    other tools: lines without a stamp are paced 100 ms apart from the
    last known stamp, which keeps mixed files monotonic.
    """
    out, clock = [], 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            stamp, tab, rest = line.partition("\t")
            if tab and stamp.isdigit():
                clock = int(stamp)
                frames = rest
            else:
                clock += 100
                frames = line
            for frame in frames.split(SEP):
                if frame:
                    out.append((clock, frame))
    return out


def run(path_pattern: str, max_tries: int = 8) -> None:
    """Record until told to stop, surviving what the wire does.

    A dropped socket is retried with exponential backoff and jitter (a
    fleet of reconnecting clients must not knock in unison); a session
    turnover rotates to a fresh file named by the pattern's ``{n}`` and
    resets the backoff, because a new session is a fresh start, not a
    fault.
    """
    n, tries = 0, 0
    while tries < max_tries:
        target = path_pattern.format(n=n)
        try:
            record(target)
        except SessionTurnover:
            n, tries = n + 1, 0
            continue
        except (ConnectionError, OSError):
            tries += 1
            time.sleep(min(2 ** tries, 60) * (0.5 + random.random()))
