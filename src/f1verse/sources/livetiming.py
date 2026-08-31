# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Direct client for the official live-timing static archive.

Session paths are discovered via the season ``Index.json``, so no
third-party library is involved. Nothing is redistributed — clips stay as
URLs.
"""
import base64
import json
import re
import zlib

from .. import http

BASE = "https://livetiming.formula1.com"
_LINE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}\.\d{3})(.*)$")


def api_path(year: int, meeting_name: str, session_name: str = "Race") -> str:
    # the season index gains sessions as the year runs
    idx = http.get_json(f"{BASE}/static/{year}/Index.json",
                        ttl=http.TTL_SCHEDULE)
    for m in idx.get("Meetings", []):
        if meeting_name.lower() in m.get("Name", "").lower():
            for s in m.get("Sessions", []):
                if s.get("Name") == session_name and s.get("Path"):
                    return "/static/" + s["Path"]
    raise LookupError(f"{year} {meeting_name!r} {session_name!r} not in Index")


def fetch_stream(path: str, filename: str) -> list:
    """A ``.jsonStream`` file → ``[(t_seconds, payload_dict), ...]``."""
    out = []
    for line in http.get_text(BASE + path + filename).splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        try:
            out.append((t, json.loads(m.group(4))))
        except json.JSONDecodeError:
            continue
    return out


def deepmerge(base, patch):
    """Streams send one snapshot, then partial patches.

    One wrinkle matters for correctness: a patch aimed at a *list* arrives
    as a dict whose keys are stringified indices — ``{"2": {...}}`` means
    "merge into element 2". An index past the end appends. A patch whose
    keys are not indices simply replaces the list, and two lists never
    concatenate; the later one wins.
    """
    if isinstance(base, list) and isinstance(patch, dict):
        for k, v in patch.items():
            try:
                i = int(k)
            except (TypeError, ValueError):
                return patch
            if 0 <= i < len(base):
                base[i] = deepmerge(base[i], v)
            else:
                base.append(deepmerge(None, v))
        return base
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    for k, v in patch.items():
        base[k] = deepmerge(base.get(k), v)
    return base


def unpack_z(payload: str):
    """The two ``.z`` channels (car data, position) wrap their JSON in
    base64 over headerless DEFLATE — plain ``zlib.decompress`` refuses it
    unless told not to expect a header."""
    raw = zlib.decompress(base64.b64decode(payload.strip('"')),
                          -zlib.MAX_WBITS)
    return json.loads(raw.decode("utf-8"))
