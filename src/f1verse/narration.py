# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Grounded text generation — facts stay in Python, wording comes from a model.

The division of labour is deliberate and strict:

1. **Python computes.** Every number is calculated, rounded and *formatted
   into its final string* before generation begins. Language models are
   measurably worse at arithmetic embedded in prose than at isolated sums,
   so they are never asked to do any.
2. **Templates carry the skeleton.** Repetitive lines ("Lap 32: VER pits,
   2.4s") are pure string formatting. They cost nothing and never drift.
3. **A model varies the wording** — and only that. It receives structured
   facts and may quote them; it may not invent, recompute or round them.

Generation is optional. Nothing in f1verse requires a model: ``brief()``
produces publishable text on its own, and is also the fallback whenever a
generated draft fails verification.
"""
from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path
from typing import Callable, Iterable

from ._json import jsonsafe

# Numbers in prose: 12, 4.312, 1:31.421, 2:04:44.859
_NUMBER = re.compile(r"\d+(?::\d+)*(?:\.\d+)?")


# ─────────────────────────────────────────── facts

def race_facts(race) -> dict:
    """The fact sheet a narrator is allowed to quote.

    Every value that could appear in a sentence is pre-formatted here, so
    the narrator copies strings rather than deciding how to round them.
    """
    results = race.results()
    podium = [r for r in results if r["position"] and r["position"] <= 3]
    led = race.laps_led()
    ev = race.story()["event"]
    inter = race.interruptions()
    pace = race.race_pace()

    def pace_str(seconds):
        return f"{int(seconds // 60)}:{seconds % 60:06.3f}"

    return jsonsafe({
        "event": {"name": ev["name"], "location": ev["location"],
                  "round": ev["round"], "laps": ev["total_laps"]},
        "podium": [{"position": r["position"], "driver": r["abbr"],
                    "name": r["name"], "team": r["team"], "gap": r["gap"]}
                   for r in podium],
        "laps_led": [{"driver": d, "laps": n} for d, n in led.items()],
        "most_laps_led": (lambda k: {"driver": k, "laps": led[k]})(next(iter(led)))
        if led else None,
        "lead_changes": max(len(race.leader_runs()) - 1, 0),
        "retirements": [{"driver": r["abbr"]} for r in results
                        if r["gap"] in ("DNF", "DNS")],
        "retirement_count": sum(r["gap"] in ("DNF", "DNS") for r in results),
        "fastest_pace": ([{"driver": d, "median_lap": pace_str(v)}
                          for d, v in list(pace.items())[:3]]),
        "interruptions": {
            "red_flag_laps": inter["red_flag_laps"],
            "sc_vsc_periods": [{"from": a, "to": b}
                               for a, b in inter["sc_vsc_bands"]],
        },
    })


# ─────────────────────────────────────────── deterministic text

def brief(race, facts: dict | None = None) -> str:
    """A publishable summary built purely from templates — no model, no cost.

    Also the fallback when generated text fails verification: a plain
    sentence is always better than a wrong one.
    """
    f = facts or race_facts(race)
    ev, lines = f["event"], []
    lines.append(f"{ev['name']}, {ev['laps']} laps at {ev['location']}.")

    if f["podium"]:
        win = f["podium"][0]
        lines.append(f"{win['name']} ({win['team']}) won.")
        rest = ", ".join(f"{p['name']} {p['gap']}" for p in f["podium"][1:])
        if rest:
            lines.append(f"Behind: {rest}.")

    most = f["most_laps_led"]
    if most and f["podium"] and most["driver"] != f["podium"][0]["driver"]:
        lines.append(f"{most['driver']} led the most laps ({most['laps']}), "
                     f"not the winner.")
    if f["lead_changes"]:
        lines.append(f"The lead changed {f['lead_changes']} times.")
    if f["interruptions"]["red_flag_laps"]:
        laps = ", ".join(str(l) for l in f["interruptions"]["red_flag_laps"])
        lines.append(f"Red flag on lap {laps}.")
    for p in f["interruptions"]["sc_vsc_periods"]:
        if p["from"] == p["to"]:
            lines.append(f"Safety car or VSC on lap {p['from']}.")
        else:
            lines.append(f"Safety car or VSC from lap {p['from']} to {p['to']}.")
    if f["retirements"]:
        who = ", ".join(r["driver"] for r in f["retirements"])
        lines.append(f"{len(f['retirements'])} cars retired: {who}.")
    return " ".join(lines)


# ─────────────────────────────────────────── verification

def _allowed_numbers(obj) -> set:
    """Every numeric token appearing anywhere in the fact sheet."""
    found = set()
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif o is not None:
            found.update(_NUMBER.findall(str(o)))
    walk(obj)
    return found


def unsupported_numbers(text: str, facts: dict) -> list:
    """Numbers in *text* that do not appear in *facts*.

    A whitelist check, not a blacklist: anything the fact sheet cannot
    account for is treated as invented. Empty list means the text is safe
    to publish.
    """
    return sorted(set(_NUMBER.findall(text)) - _allowed_numbers(facts))


# Codes that are terminology, not driver identifiers.
_RESERVED = {"VSC", "DNF", "DNS", "DSQ", "GMT", "UTC", "FIA"}


def _allowed_codes(obj) -> set:
    """Three-letter codes appearing anywhere in the fact sheet.

    Collected from the whole structure rather than a chosen few fields —
    a retiring driver is as legitimate a subject as a podium finisher, and
    hardcoding a subset turns valid text into a false alarm.
    """
    codes = set()
    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            codes.update(re.findall(r"\b[A-Z]{3}\b", o))
    walk(obj)
    return codes


def verify(text: str, facts: dict, *, names: Iterable[str] = ()) -> dict:
    """Check generated text against the fact sheet.

    Returns ``{"ok": bool, "unsupported_numbers": [...],
    "unknown_names": [...]}``. Cheap, deterministic, and run on every
    draft — a wrong number reaching publication costs more than any
    number of regenerations.
    """
    if not isinstance(text, str):
        raise TypeError("draft must be a string")
    bad_nums = unsupported_numbers(text, facts)
    known = {str(n) for n in names} if names else _allowed_codes(facts)
    unknown = sorted(w for w in set(re.findall(r"\b[A-Z]{3}\b", text))
                     if w not in known and w not in _RESERVED)
    approved = {s.rstrip(".; ") for s in _approved_phrases(facts)}
    sentences = [s.strip().rstrip(".; ") for s in
                 re.split(r"(?<=[.;])\s+", text.strip()) if s.strip()]
    unverified = [s for s in sentences if s not in approved]
    if not sentences:
        unverified = ["empty draft or invalid fact selection"]
    return {"ok": bool(sentences) and not bad_nums and not unknown and not unverified,
            "unsupported_numbers": bad_nums, "unknown_names": unknown,
            "unverified_claims": unverified,
            "scope": "exact fact-bound phrases; arbitrary prose is not verified"}


def fact_catalog(facts: dict) -> dict:
    """Stable claim IDs bound to deterministic text and fact-sheet paths.

    A generator selects IDs; Python joins the driver, value and unit.
    Changing a value changes the text, not the identity of its claim.
    """
    claims = {}

    def add(key, text, paths):
        claims[key] = {"text": text, "evidence": paths, "kind": "observed"}

    ev = facts.get("event", {})
    if all(k in ev for k in ("name", "laps", "location")):
        add("event.summary", f"{ev['name']}, {ev['laps']} laps at {ev['location']}.",
            ["event.name", "event.laps", "event.location"])
    podium = sorted(facts.get("podium", []), key=lambda r: r["position"])
    if podium and podium[0]["position"] == 1:
        w = podium[0]
        add("result.winner", f"{w['name']} ({w['team']}) won.", ["podium.0"])
        if len(podium) > 1:
            add("result.behind", "Behind: " + ", ".join(
                f"{p['name']} {p['gap']}" for p in podium[1:]) + ".", ["podium"])
    for i, row in enumerate(facts.get("laps_led", [])):
        add(f"led.{row['driver']}", f"{row['driver']} led {row['laps']} laps.",
            [f"laps_led.{i}"])
    most = facts.get("most_laps_led")
    if most and podium and most["driver"] != podium[0]["driver"]:
        add("led.most", f"{most['driver']} led the most laps ({most['laps']}), "
            "not the winner.", ["most_laps_led", "podium.0"])
    if facts.get("lead_changes"):
        add("lead.changes", f"The lead changed {facts['lead_changes']} times.",
            ["lead_changes"])
    inter = facts.get("interruptions", {})
    if inter.get("red_flag_laps"):
        add("flags.red", "Red flag on lap " + ", ".join(
            str(l) for l in inter["red_flag_laps"]) + ".", ["interruptions.red_flag_laps"])
    for i, row in enumerate(inter.get("sc_vsc_periods", [])):
        span = (f"on lap {row['from']}" if row["from"] == row["to"] else
                f"from lap {row['from']} to {row['to']}")
        add(f"flags.neutralised.{i}", f"Safety car or VSC {span}.",
            [f"interruptions.sc_vsc_periods.{i}"])
    retired = facts.get("retirements", [])
    if retired:
        add("result.retirements", f"{len(retired)} cars retired: " +
            ", ".join(r["driver"] for r in retired) + ".", ["retirements"])
    return jsonsafe(claims)


def _approved_phrases(facts):
    phrases = {r["text"] for r in fact_catalog(facts).values()}
    podium = facts.get("podium", [])
    identities = {}
    for row in podium:
        name = str(row.get("name") or row["driver"])
        identities[row["driver"]] = {row["driver"], name, name.split()[-1]}
    for row in podium:
        if row["position"] == 1:
            for alias in identities[row["driver"]]:
                phrases.add(f"{alias} won.")
                if "laps" in facts.get("event", {}):
                    ev = facts["event"]
                    phrases.add(f"{alias} won over {ev['laps']} laps.")
                    phrases.add(f"{alias} won the {ev['name']} over {ev['laps']} laps.")
    for row in facts.get("laps_led", []):
        for alias in identities.get(row["driver"], {row["driver"]}):
            phrases.add(f"{alias} led {row['laps']}.")
            phrases.add(f"{alias} led {row['laps']} laps.")
    for row in facts.get("retirements", []):
        phrases.add(f"{row['driver']} retired.")
    return phrases


def _render_selection(draft, facts):
    """Accept only ID selection JSON or the limited legacy phrase grammar."""
    try:
        selection = json.loads(draft)
    except (ValueError, TypeError):
        return draft, []
    claims = fact_catalog(facts)
    if (not isinstance(selection, dict) or set(selection) != {"fact_ids"}
            or not isinstance(selection["fact_ids"], list)
            or not selection["fact_ids"] or len(selection["fact_ids"]) > len(claims)
            or any(not isinstance(k, str) or k not in claims
                   for k in selection["fact_ids"])):
        return "", []
    ids = list(dict.fromkeys(selection["fact_ids"]))
    return " ".join(claims[k]["text"] for k in ids), ids


# ─────────────────────────────────────────── generation

INSTRUCTIONS = """Select the most useful claims for a short factual race summary.

Rules:
1. Use only the numbers in the JSON below. Copy the strings exactly.
2. Do no arithmetic. Never compute differences, totals, averages or
   percentages.
3. Do not mention any number that is not in the JSON.
4. If a fact you want is missing, leave that sentence out.
5. Plain, unembellished prose. No superlatives, no invented drama."""
INSTRUCTIONS += ('\nReturn only JSON: {"fact_ids": ["result.winner", ...]}. '
                 'Select IDs from _claims. Do not write or modify claim text.')


def prompt(facts: dict) -> str:
    """The user-side prompt: instructions, then facts as JSON.

    JSON rather than prose is not a style preference — structured input
    measurably reduces factual errors in sports summarisation, at no cost.
    Keys are sorted so the same race always produces the same prompt,
    which makes provider-side prefix caching and local exact-match caching
    both work.
    """
    return (INSTRUCTIONS + "\n\nFacts:\n"
            + json.dumps({**facts, "_claims": fact_catalog(facts)},
                         ensure_ascii=False, sort_keys=True, indent=1))


def _cache_file(cache_dir, prompt_text: str) -> Path:
    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()
    return Path(cache_dir) / f"{digest}.json"


def narrate(race, generate: Callable[[str], str], *, attempts: int = 2,
            cache_dir=None) -> dict:
    """Generate a summary with *generate*, verifying every draft.

    ``generate`` takes a prompt string and returns text; f1verse does not
    talk to any provider itself, so any client or model works.

    Falls back to :func:`brief` when no draft passes. With ``cache_dir``,
    only verified drafts are stored under an exact prompt hash; similar
    races never share text. Returns the text used, its source
    (``"generated"``, ``"cache"`` or ``"template"``), and verification
    reports.
    """
    facts = race_facts(race)
    p = prompt(facts)
    reports = []
    cache_file = _cache_file(cache_dir, p) if cache_dir is not None else None
    if cache_file and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))["text"]
            report = verify(cached, facts)
            if report["ok"]:
                return jsonsafe({"text": cached, "source": "cache",
                                 "facts": facts, "attempts": [report]})
        except (KeyError, TypeError, ValueError, OSError):
            pass
    for _ in range(min(max(attempts, 1), 2)):
        try:
            draft = generate(p)
        except (OSError, RuntimeError) as exc:
            reports.append({"ok": False, "generation_error": type(exc).__name__})
            break
        if not isinstance(draft, str):
            reports.append({"ok": False, "generation_error": "callback must return a string"})
            break
        text, ids = _render_selection(draft, facts)
        report = verify(text, facts)
        report["fact_ids"] = ids
        reports.append(report)
        if report["ok"]:
            if cache_file:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_file.with_suffix(".tmp")
                temporary.write_text(json.dumps({"text": text}, ensure_ascii=False),
                                     encoding="utf-8")
                temporary.replace(cache_file)
            return jsonsafe({"text": text, "source": "generated",
                             "facts": facts, "attempts": reports})
    return jsonsafe({"text": brief(race, facts), "source": "template",
                     "facts": facts, "attempts": reports})
