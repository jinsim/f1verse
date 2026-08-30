"""Direct client for the official live-timing static archive.

Session paths are discovered via the season ``Index.json``, so no
third-party library is involved. Nothing is redistributed — clips stay as
URLs.
"""
import json
import re

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
    """Streams send one snapshot, then partial patches."""
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    for k, v in patch.items():
        base[k] = deepmerge(base.get(k), v)
    return base
