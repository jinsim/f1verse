# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""FIA decision documents — the primary source behind every penalty.

The FIA publishes stewards' decisions, classifications and technical
delegate reports as PDFs. Fans hunting for "who changed which power-unit
part" or "why was that penalty given" are told to go dig through fia.com.
This module indexes those documents so a timeline event can link to its
own evidence. Only URLs and titles are collected — no PDFs are mirrored.
"""
from __future__ import annotations

import html
import re
import urllib.parse

from . import http
from ._json import jsonsafe

BASE = "https://www.fia.com"
_SEASON = ("/documents/championships/fia-formula-one-world-championship-14"
           "/season/season-{key}")

# The season is chosen by this id, **not** by the year in the URL — the year
# segment is decorative and the site ignores it. Get the id wrong and the
# request still returns 200 with a full page, just of the wrong season, which
# is why an unknown year raises here instead of falling back to a default.
_SEASON_KEY = {
    2026: 2072, 2025: 2071, 2024: 2043, 2023: 2042,
    2022: 2005, 2021: 1108, 2020: 1059,
}
_HREF = re.compile(r'href="(/system/files/decision-document/[^"]+\.pdf)"')
_EVENT = re.compile(r'value="(/documents/[^"]*?/event/[^"]+)"')

_KIND = (
    ("power_unit", ("power unit", "pu element", "engine")),
    ("penalty", ("infringement", "penalty", "decision")),
    ("classification", ("classification", "championship points")),
    ("scrutineering", ("scrutineering", "technical delegate")),
    ("grid", ("starting grid", "pit lane start")),
)


def _classify(title: str) -> str:
    t = title.lower()
    for kind, keys in _KIND:
        if any(k in t for k in keys):
            return kind
    return "other"


def _season_path(year: int) -> str:
    if year not in _SEASON_KEY:
        raise LookupError(
            f"no FIA season id known for {year}; indexed seasons are "
            f"{', '.join(str(y) for y in sorted(_SEASON_KEY))}")
    return BASE + _SEASON.format(key=_SEASON_KEY[year])


def events(year: int = 2026) -> list:
    """The events of a season, newest first, as the site names them.

    The names are what :func:`documents` takes as its ``event`` argument —
    "Dutch Grand Prix", not "zandvoort".
    """
    page = http.get_text(_season_path(year), ttl=http.TTL_SCHEDULE)
    seen, out = set(), []
    for path in _EVENT.findall(page):
        name = urllib.parse.unquote(path.rsplit("/event/", 1)[-1])
        if name not in seen:
            seen.add(name)
            out.append(name)
    return jsonsafe(out)


def _harvest(page: str, event_name: str | None, seen: set) -> list:
    out = []
    for path in _HREF.findall(page):
        if path in seen:
            continue
        seen.add(path)
        slug = path.rsplit("/", 1)[-1][:-4]
        title = html.unescape(slug.replace("_", " ").replace("-", " ")).strip()
        out.append({"title": title, "kind": _classify(title),
                    "event": event_name, "url": BASE + path, "file": slug})
    return out


def documents(year: int = 2026, event: str | None = None) -> list:
    """Index a season's decision documents.

    The season landing page only ever shows the **most recent event**, so
    indexing a whole season means walking the event list — one request per
    event, paced by the HTTP layer. Pass ``event`` to fetch just one; the
    name is matched loosely, so ``"dutch"`` finds "Dutch Grand Prix".

    Every row carries the ``event`` it came from, because a document title
    alone does not always say.
    """
    names = events(year)
    if event:
        wanted = [n for n in names if event.lower() in n.lower()]
        if not wanted:
            raise LookupError(
                f"no {year} event matching {event!r}; that season had "
                f"{', '.join(names)}")
    else:
        wanted = names
    base, seen, out = _season_path(year), set(), []
    for name in wanted:
        page = http.get_text(f"{base}/event/{urllib.parse.quote(name)}")
        out += _harvest(page, name, seen)
    return jsonsafe(out)


def power_unit_documents(year: int = 2026) -> list:
    """Just the power-unit element documents — the "engine usage" question
    the community keeps asking, answered from the primary source."""
    return [d for d in documents(year) if d["kind"] == "power_unit"]
