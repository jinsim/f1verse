"""FIA decision documents — the primary source behind every penalty.

The FIA publishes stewards' decisions, classifications and technical
delegate reports as PDFs. Fans hunting for "who changed which power-unit
part" or "why was that penalty given" are told to go dig through fia.com.
This module indexes those documents so a timeline event can link to its
own evidence. Only URLs and titles are collected — no PDFs are mirrored.
"""
import html
import re

from . import http
from ._json import jsonsafe

BASE = "https://www.fia.com"
_SEASON = ("/documents/championships/fia-formula-one-world-championship-14"
           "/season/season-{year}-{key}")
# season page ids are not derivable from the year alone
_SEASON_KEY = {2026: 2071, 2025: 2071}
_HREF = re.compile(r'href="(/system/files/decision-document/[^"]+\.pdf)"')

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


def documents(year: int = 2026, event: str | None = None) -> list:
    """Index the season's decision documents.

    Args:
        year: season to index.
        event: optional substring filter, e.g. ``"dutch"``.
    """
    key = _SEASON_KEY.get(year, 2071)
    page = http.get_text(BASE + _SEASON.format(year=year, key=key))
    seen, out = set(), []
    for path in _HREF.findall(page):
        if path in seen:
            continue
        seen.add(path)
        slug = path.rsplit("/", 1)[-1][:-4]
        title = html.unescape(slug.replace("_", " ").replace("-", " ")).strip()
        if event and event.lower() not in title.lower():
            continue
        out.append({"title": title, "kind": _classify(title),
                    "url": BASE + path, "file": slug})
    return jsonsafe(out)


def power_unit_documents(year: int = 2026) -> list:
    """Just the power-unit element documents — the "engine usage" question
    the community keeps asking, answered from the primary source."""
    return [d for d in documents(year) if d["kind"] == "power_unit"]
