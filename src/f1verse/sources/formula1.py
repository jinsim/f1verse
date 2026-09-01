# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Circuit specifications from the championship's own race pages.

Secondary references copy each other, so several of them carrying the same
figure is not corroboration. It is one claim, repeated. Two of the numbers
this library first took from such reports were simply wrong — a 5474 m lap
that is officially 5416 m, a 4940 m one that is officially 4927 m — and
nothing about how widely they circulated hinted at it.

The championship publishes the figures itself, one page per event, and the
season index lists every event, so the whole calendar is reachable without
anyone maintaining a table of URLs.

There is no separate data API behind those pages — the site renders on the
server — but it does embed a structured description of the event, and that
is what identity is taken from here: the official circuit name, the
location, the country and the event key. That key is the same one the
timing feed uses, so an event page joins to a session exactly rather than
by matching names, which never survives contact with a calendar where one
country holds three races and two feeds spell Lusail differently.

The specifications themselves are read from the page's own definition
list, label by label, rather than by pattern-matching prose. That is
sturdier than it sounds — the label is the markup — but it is still a
rendered page, so every value is range-checked and anything that no longer
parses yields nothing rather than a plausible number. Because of that this
is meant to be run deliberately, to refresh the curated table where a
person sees the result, and not on the path of an ordinary query.
"""
from __future__ import annotations

import html
import json
import re

from .. import http

SEASON = "https://www.formula1.com/en/racing/{year}"
CIRCUIT = "https://www.formula1.com/en/racing/{year}/{slug}/circuit"

# Refreshing the table is a deliberate act, but the pages are still worth
# holding briefly so that one sweep does not fetch the same event twice.
TTL_PAGE = 24 * 60 * 60

# A Formula 1 lap is neither a kart track nor the old Nürburgring, and a
# race is a few hundred kilometres over a few dozen laps. Anything outside
# these is a parse that has gone wrong, not a circuit.
LIMITS = {
    "length_m": (2000, 8000),
    "race_laps": (20, 90),
    "race_distance_km": (150.0, 400.0),
    "first_grand_prix": (1950, 2100),
}

_NOT_A_RACE = ("testing", "test")


def _page(url: str) -> str:
    return http.get_text(url, ttl=TTL_PAGE)


def _text(url: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", _page(url))
    return re.sub(r"\s+", " ", html.unescape(stripped))


def _definitions(markup: str) -> dict:
    """The page's ``<dt>label</dt><dd>value</dd>`` pairs, as a mapping."""
    pairs = re.findall(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>",
                       markup, re.S)
    out = {}
    for label, value in pairs:
        key = html.unescape(re.sub(r"<[^>]+>", "", label)).strip()
        text = html.unescape(re.sub(r"<[^>]+>", "", value)).strip()
        if key and key not in out:
            out[key] = text
    return out


def _embedded_event(markup: str) -> dict:
    """The event description the page carries alongside its markup.

    Identity and schedule as the championship itself records them: the
    official circuit, where it actually is, the event key the timing feed
    shares, and the scheduled lap count and distance.
    """
    flat = markup.replace('\\"', '"')
    # a page embeds the event more than once and the copies do not carry
    # the same fields — one names the circuit, another the meeting — so
    # they are combined rather than chosen between
    merged = {}
    for match in re.finditer(r'"circuitOfficialName"', flat):
        for key, value in _object_around(flat, match.start()).items():
            if value not in (None, "") and not isinstance(value, (dict, list)):
                merged.setdefault(key, value)
    return merged


def _object_around(flat: str, anchor: int) -> dict:
    opening = flat.rfind("{", 0, anchor)
    if opening < 0:
        return {}
    # brace counting has to ignore braces inside strings, and these
    # payloads carry names like "Circuit de Spa-Francorchamps {old}"
    depth, in_string, escaped = 0, False, False
    for index in range(opening, len(flat)):
        char = flat[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
        elif char == '"':
            in_string = not in_string
        elif not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(flat[opening:index + 1])
                    except ValueError:
                        return {}
                    return parsed if isinstance(parsed, dict) else {}
    return {}


def _within(field: str, value):
    low, high = LIMITS[field]
    return value if value is not None and low <= value <= high else None


def season_slugs(year: int) -> list:
    """Every race the championship lists for a season, as URL slugs.

    Pre-season tests share the index with the races and are dropped: they
    are events, not circuits with a race distance.
    """
    found = re.findall(r"/en/racing/%d/([a-z0-9\-]+)" % year, _text(
        SEASON.format(year=year)))
    # calendar order, not alphabetical: the index lists the season as it
    # runs, which is what lets an event be matched to a round
    ordered = []
    for slug in found:
        if slug not in ordered and not any(w in slug for w in _NOT_A_RACE):
            ordered.append(slug)
    return ordered


def circuit_specs(year: int, slug: str) -> dict:
    """Length, race laps, race distance and first Grand Prix for one event.

    Fields that cannot be read, or that read as something no Formula 1
    circuit could be, come back as ``None``.
    """
    url = CIRCUIT.format(year=year, slug=slug)
    markup = _page(url)
    listed = _definitions(markup)
    event = _embedded_event(markup)

    def _number(label: str, pattern: str):
        match = re.search(pattern, listed.get(label, ""))
        return match.group(1) if match else None

    length_km = _number("Circuit Length", r"([\d.]+)\s*km")
    laps = _number("Number of Laps", r"(\d+)")
    distance = _number("Race Distance", r"([\d.]+)\s*km")
    first = _number("First Grand Prix", r"(\d{4})")

    def _float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    metres = _float(length_km)
    specs = {
        "slug": slug,
        # identity, so a caller never has to match on a name
        "meeting_key": event.get("meetingKey"),
        "circuit_key": event.get("circuitKey"),
        "circuit_official_name": event.get("circuitOfficialName"),
        "circuit_short_name": event.get("circuitShortName"),
        "circuit_type": event.get("circuitType"),
        # where the race is actually held, which is not always what the
        # event is named after: a Grand Prix can carry one country's name
        # and be run in another
        "circuit_location": event.get("circuitLocation"),
        "location": event.get("meetingLocation"),
        "country": event.get("meetingIsoCountryName") or
                   event.get("meetingCountryName"),
        "meeting_official_name": event.get("meetingOfficialName"),
        "length_m": _within("length_m", round(metres * 1000) if metres else None),
        "race_laps": _within("race_laps", _int(laps)),
        "race_distance_km": _within("race_distance_km", _float(distance)),
        "first_grand_prix": _within("first_grand_prix", _int(first)),
        "source": f"formula1.com official circuit page, {year} {slug}",
        "source_url": url,
    }
    specs["available"] = specs["length_m"] is not None
    return specs


def season_specs(year: int) -> dict:
    """Specifications for every event of a season, keyed by slug.

    One unreadable page does not stop the sweep; it is reported with
    ``available`` false so a caller can see which events came back empty.
    """
    out = {}
    for slug in season_slugs(year):
        try:
            out[slug] = circuit_specs(year, slug)
        except Exception as error:
            out[slug] = {"slug": slug, "available": False,
                         "reason": f"{type(error).__name__}: {error}"}
    return out
