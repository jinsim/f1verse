# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Structured circuit facts, taken from the upstream rather than a copy.

Aggregated Formula 1 databases carry circuit specifications, but they are
themselves compilations: hand-maintained, and in the general case without
naming where a figure came from. Depending on one means inheriting both
its licence terms and its unstated provenance.

There is a shorter path. The historical results feed already hands over a
Wikipedia article for every circuit it knows, and a Wikipedia article
resolves to a Wikidata entity, which holds the same specifications as
typed, sourced statements. Wikidata is CC0, so nothing is owed for using
it, and it is upstream of the compilations rather than downstream.

Only literal, checkable properties are read — a length, a founding date, a
coordinate. Values arrive with an explicit unit and are converted here so
that callers never have to; a statement in an unrecognised unit is
dropped rather than assumed to be metres.
"""
from __future__ import annotations

import urllib.parse

from .. import http

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
ENTITY_DATA = "https://www.wikidata.org/wiki/Special:EntityData/"

# Circuit specifications outlive a season but do not outlive a rebuild, so
# they expire slowly rather than never. A circuit that is shortened over a
# winter must not be served from a cache taken before it.
TTL_SPEC = 30 * 24 * 60 * 60

# Wikidata identifies units by entity, not by name.
_METRES = {
    "Q11573": 1.0,          # metre
    "Q828224": 1000.0,      # kilometre
    "Q253276": 1609.344,    # mile
}

LENGTH = "P2043"
INCEPTION = "P571"
COORDINATES = "P625"


def entity_id(wikipedia_url: str) -> str | None:
    """The Wikidata entity behind an English Wikipedia article."""
    if not wikipedia_url or "/wiki/" not in wikipedia_url:
        return None
    title = wikipedia_url.rsplit("/wiki/", 1)[1]
    # An article link arrives as it would be typed into a browser: the
    # title percent-encoded, and sometimes carrying the section that was
    # actually being cited. The API wants neither.
    title = urllib.parse.unquote(title.split("#", 1)[0])
    payload = http.get_json(WIKIPEDIA_API, {
        "action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
        # article titles held by other feeds age into redirects; following
        # them is the difference between a fact and a gap
        "redirects": "1",
        "format": "json", "titles": title}, ttl=TTL_SPEC)
    pages = (payload.get("query") or {}).get("pages") or {}
    for page in pages.values():
        item = (page.get("pageprops") or {}).get("wikibase_item")
        if item:
            return item
    return None


def _first(claims: dict, prop: str):
    for statement in claims.get(prop) or []:
        value = (statement.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if value is not None:
            return value
    return None


def circuit_facts(wikipedia_url: str) -> dict:
    """Length, opening date and position for one circuit.

    Absent properties come back as ``None``. A length carried in a unit
    this module does not recognise is treated as absent too — a number
    without a trustworthy unit is worse than no number.
    """
    qid = entity_id(wikipedia_url)
    if not qid:
        return {"available": False,
                "reason": "no Wikidata entity for this article"}
    payload = http.get_json(f"{ENTITY_DATA}{qid}.json", ttl=TTL_SPEC)
    entity = (payload.get("entities") or {}).get(qid) or {}
    claims = entity.get("claims") or {}

    length_m = None
    raw_length = _first(claims, LENGTH)
    if isinstance(raw_length, dict):
        unit = (raw_length.get("unit") or "").rsplit("/", 1)[-1]
        scale = _METRES.get(unit)
        try:
            amount = float(raw_length.get("amount"))
        except (TypeError, ValueError):
            amount = None
        if scale and amount is not None:
            length_m = round(amount * scale)

    opened = None
    raw_time = _first(claims, INCEPTION)
    if isinstance(raw_time, dict) and raw_time.get("time"):
        opened = raw_time["time"].lstrip("+")[:4]

    point = _first(claims, COORDINATES)
    coordinates = ({"lat": point.get("latitude"), "lon": point.get("longitude")}
                   if isinstance(point, dict) else None)

    return {
        "available": length_m is not None or opened is not None,
        "wikidata_id": qid,
        "length_m": length_m,
        "opened": opened,
        "coordinates": coordinates,
        "source": f"Wikidata {qid} (CC0)",
        "source_url": f"https://www.wikidata.org/wiki/{qid}",
    }
