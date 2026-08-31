#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Build the documentation site — standard library, like everything else.

The site exists to be read by two audiences that want opposite things.
A person wants a tour; a retrieval system wants one page per question,
with the answer in the first two sentences, because that is the span it
extracts and it cites only a handful of sources. So each question here is
its own page and each page opens with the answer.

    python scripts/build_docs.py [outdir]      # default: site/

Output is not committed; ``.github/workflows/docs.yml`` builds and deploys
it to GitHub Pages on every push to main.
"""
from __future__ import annotations

import html
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = "https://jinsim.github.io/f1verse"
REPO = "https://github.com/jinsim/f1verse"
TAGLINE = ("The story layer for Formula 1 data — zero-dependency Python "
           "library and MCP server.")

sys.path.insert(0, str(ROOT / "src"))
from f1verse import _tools                                     # noqa: E402
from f1verse._version import __version__                       # noqa: E402


class Page:
    """One question, answered before anything else on the page."""

    def __init__(self, slug, title, question, answer, code, notes=(),
                 related=()):
        self.slug = slug            # "" for the index
        self.title = title          # browser tab / search result title
        self.question = question    # H1 — phrased the way people type it
        self.answer = answer        # 1-2 sentences, extractable on its own
        self.code = code
        self.notes = notes          # paragraphs of "why this is the answer"
        self.related = related

    @property
    def url(self):
        return f"{SITE}/{self.slug}/" if self.slug else f"{SITE}/"


PAGES = [
    Page(
        "f1-race-results-python",
        "Get Formula 1 race results in Python",
        "How do I get Formula 1 race results in Python?",
        "Install <code>f1verse</code> and call <code>load(year, round)</code>. "
        "It has no dependencies and needs no API key, client object or "
        "configuration — the results come back as plain dictionaries.",
        'pip install f1verse\n\n'
        '>>> import f1verse\n'
        '>>> race = f1verse.load(2026, 12)\n'
        '>>> race.results()[7]\n'
        "{'position': 8, 'abbr': 'HUL', 'team': 'Kick Sauber', 'gap': '+1 LAP', ...}",
        notes=[
            "Gaps follow the broadcast convention rather than raw arithmetic: a "
            "lapped car reads <code>+1 LAP</code>, not a time. That is a domain "
            "rule, not an option — getting it wrong is the most common way a "
            "generated results table becomes subtly false.",
            "Round numbers are 1-based within the season. If you only know "
            "“the last race”, resolve it first with "
            "<code>f1verse.status(2026)</code>.",
        ],
        related=["f1-race-json-one-call", "f1-results-final", "f1-qualifying-gaps"],
    ),
    Page(
        "f1-race-json-one-call",
        "A whole F1 race as JSON in one call",
        "How do I get an entire F1 race as JSON in one call?",
        "Call <code>race.story()</code>. One request returns results, lead "
        "changes, laps led, the event timeline, tyre stints, race pace and "
        "safety-car interruptions as a single JSON-safe dictionary.",
        '>>> race = f1verse.load(2026, 12)\n'
        '>>> story = race.story()\n'
        '>>> sorted(story)\n'
        "['event', 'interruptions', 'laps_led', 'leader_runs', 'race_pace',\n"
        " 'results', 'schema_version', 'sources', 'state', 'stints', 'timeline']\n"
        '>>> json.dumps(story)          # never raises',
        notes=[
            "Every public return value in f1verse is JSON-safe by construction, "
            "so nothing has to be coaxed out of a dataframe or a custom class "
            "before it reaches a template, a queue or a language model.",
            "<code>race_pace()</code> inside the story is a median with pit, "
            "safety-car and virtual-safety-car laps already excluded. Pace that "
            "includes a pit lap is not pace.",
        ],
        related=["f1-mcp-server", "f1-race-results-python", "grounded-f1-summaries"],
    ),
    Page(
        "f1-results-final",
        "Know when F1 results are final",
        "How do I know when Formula 1 results are final?",
        "Call <code>race.quality_report()</code>. It returns a lifecycle state "
        "— provisional, settled, final or corrected — alongside per-field "
        "completeness, the age of the fetched copy and a single "
        "<code>publishable</code> verdict.",
        '>>> race.quality_report()\n'
        "{'state': 'final',\n"
        " 'coverage': {'overall': 0.9955, 'sectors': 0.9824, 'compound': 1.0},\n"
        " 'source_age_seconds': 312,\n"
        " 'revisions': [],\n"
        " 'publishable': True}",
        notes=[
            "The chequered flag is not the classification. Scrutineering "
            "disqualifications and post-race penalties land hours later and "
            "<em>rewrite rows in place</em> — a result you fetched at the flag "
            "can be wrong by dinner without anything looking broken.",
            "This is why f1verse caches by mutability rather than blanket TTL. "
            "Laps and telemetry are immutable and cached forever; anything a "
            "steward can rewrite is cached only until the session is final.",
            "A cross-source check that could not run is reported as "
            "<code>skipped</code>, never as agreement. “Nothing was "
            "compared” and “nothing disagreed” must not produce "
            "the same verdict.",
        ],
        related=["f1-detect-result-changes", "f1-crosscheck-sources", "f1-schedule-pipeline"],
    ),
    Page(
        "f1-detect-result-changes",
        "Detect when an F1 result changes",
        "How do I detect that an F1 result changed after publication?",
        "Persist <code>race.snapshot()</code> and compare it later with "
        "<code>f1verse.diff(before, after)</code>. You get a field-level list "
        "of what the source rewrote — the input to a correction notice.",
        '>>> before = race.snapshot()          # hashed, comparable, JSON\n'
        '>>> after = race.refresh().snapshot()\n'
        '>>> f1verse.diff(before, after)\n'
        "{'changed': True,\n"
        " 'changes': [{'abbr': 'HAM', 'field': 'position', 'before': 4, 'after': None},\n"
        "             {'abbr': 'HAM', 'field': 'gap', 'before': '+8.1s', 'after': 'DSQ'}]}",
        notes=[
            "Every change to a cached body is journalled: "
            "<code>f1verse.revisions()</code> lists every source rewrite this "
            "install has observed, and <code>f1verse.vintage(record)</code> "
            "returns the superseded body when it was small enough to keep.",
            "There is deliberately no <code>as_of=</code> time travel. f1verse "
            "can tell you what it sees now and when it saw a value change; it "
            "cannot reconstruct a value nobody here ever fetched.",
        ],
        related=["f1-results-final", "f1-crosscheck-sources"],
    ),
    Page(
        "f1-crosscheck-sources",
        "Cross-check F1 data against a second source",
        "How do I check Formula 1 data against an independent source?",
        "Call <code>race.crosscheck()</code>. It recomputes what it can from a "
        "second, independent feed and reports agreement, disagreement, or "
        "<code>skipped</code> when that feed does not exist for the session.",
        '>>> race.crosscheck()\n'
        "{'lapped_gaps': {'verdict': 'agree', 'checked': 4}, ...}",
        notes=[
            "Sprints publish no overtakes feed, so a check that depends on it "
            "returns <code>skipped</code>. Treating an unavailable check as a "
            "passing check is how bad data reaches an audience.",
            "Use it with <code>quality_report()</code>: crosscheck answers "
            "<em>do independent sources agree</em>; the quality report adds how "
            "complete the data is, how old the copy is, and whether the "
            "classification is still provisional.",
        ],
        related=["f1-results-final", "f1-detect-result-changes"],
    ),
    Page(
        "f1-undercut-analysis",
        "Judge whether an F1 undercut worked",
        "How do I tell whether an undercut worked, in code?",
        "Call <code>f1verse.pit_exchanges(race)</code>. It pairs the stops that "
        "actually traded track position and returns a verdict per exchange, "
        "with neutralised laps excluded.",
        '>>> f1verse.pit_exchanges(race)[0]\n'
        "{'attacker': 'RUS', 'defender': 'LEC', 'verdict': 'undercut', ...}",
        notes=[
            "A stop under a safety car is not an undercut, and counting it as "
            "one inflates every strategy summary built on top. Neutralised laps "
            "are excluded by default rather than behind a flag.",
            "What an undercut is worth is track-specific: "
            "<code>f1verse.circuit_profile(2026, 13)</code> reports pit loss "
            "split by track state — <code>{'normal': 25.43, 'sc': 16.11, "
            "'vsc': 18.4}</code>.",
        ],
        related=["f1-race-json-one-call", "f1-race-results-python"],
    ),
    Page(
        "f1-qualifying-gaps",
        "Formula 1 qualifying results and gaps in Python",
        "How do I get F1 qualifying results with the right gaps?",
        "Call <code>f1verse.load_session(year, round, \"Qualifying\")</code>. "
        "Gaps are measured to the fastest lap <em>of that segment</em>, and "
        "each driver carries the segment they were eliminated in.",
        '>>> q = f1verse.load_session(2026, 12, "Qualifying")\n'
        '>>> q.results()[0]\n'
        "{'abbr': 'NOR', 'q1': 72.695, 'q1_gap': 0.085, 'q3': 71.163,\n"
        " 'q3_gap': 0.0, 'best': 71.163, 'eliminated_in': None, ...}\n"
        '>>> q.segments()["q1"]["cut_margin"]\n'
        "0.022",
        notes=[
            "A single “gap to leader” column misreports qualifying: "
            "the pole-sitter above was 0.085 s off the fastest time in Q1. Each "
            "kind of session gets the classification it actually has.",
            "<code>f1verse.sessions(year, round)</code> lists what a weekend "
            "contained, in order — the valid inputs to "
            "<code>load_session</code>. A sprint loads as a race; sprint "
            "qualifying loads as qualifying.",
        ],
        related=["f1-race-results-python", "f1-race-json-one-call"],
    ),
    Page(
        "f1-schedule-pipeline",
        "Run an F1 data pipeline on a schedule",
        "How do I run a Formula 1 pipeline on a schedule without double-posting?",
        "Call <code>f1verse.due(year, processed=[...])</code>. It returns "
        "sessions that have finished, settled past the flag, and are not in the "
        "list of session keys you have already handled.",
        '>>> f1verse.status(2026)\n'
        "{'latest_race': {'round': 12, 'meeting': 'Dutch Grand Prix'},\n"
        " 'next': {'round': 13, 'session': 'Practice 1'}, 'next_in_hours': 125.7}\n"
        '>>> f1verse.due(2026, processed=state["done"])\n'
        "[]                       # nothing new to publish yet",
        notes=[
            "The settle window is the point: a session that ended two minutes "
            "ago is not ready to publish. Keeping the processed list on your "
            "side means nothing publishes twice and nothing is missed after "
            "downtime, without f1verse holding state for you.",
            "Zero dependencies makes this cheap to host — the whole library "
            "fits in a small serverless function with no build step and no "
            "compiled wheels.",
        ],
        related=["f1-results-final", "f1-mcp-server"],
    ),
    Page(
        "grounded-f1-summaries",
        "Write F1 race summaries an LLM cannot make up",
        "How do I generate F1 race summaries without hallucinated numbers?",
        "Build the text from <code>f1verse.race_facts(race)</code> and check the "
        "output with <code>f1verse.verify(text, facts)</code>, which rejects any "
        "number or driver code the data does not support.",
        '>>> facts = f1verse.race_facts(race)\n'
        '>>> f1verse.brief(race)            # templates only, no model, no cost\n'
        "'Dutch Grand Prix, 72 laps at Zandvoort. Lando Norris (McLaren) won. ...'\n"
        '>>> f1verse.verify(draft, facts)\n'
        "{'ok': False, 'unsupported_numbers': [1.4], 'unsupported_codes': ['VER']}",
        notes=[
            "Models never calculate race facts here. Narration receives "
            "preformatted structured facts, and a generated draft only survives "
            "if every number and driver code in it appears in those facts.",
            "<code>brief()</code> is also the fallback when generation fails "
            "verification. A plain sentence is always better than a wrong one.",
        ],
        related=["f1-mcp-server", "f1-race-json-one-call"],
    ),
    Page(
        "f1-championship-probability",
        "Calculate F1 championship win probability in Python",
        "How do I calculate F1 title win probability?",
        "Call <code>f1verse.championship_projection(year)</code>. It plays the "
        "remaining rounds out thousands of times, resampling each driver from "
        "the positions they have actually finished in, and returns a title "
        "probability with the evidence it stands on.",
        '>>> f1verse.title_scenarios(2026)["max_points_available"]\n'
        '283                        # arithmetic: who is mathematically out\n'
        '>>> f1verse.championship_projection(2026)["drivers"][0]\n'
        "{'driver': 'ANT', 'title_probability': 0.954, 'points_now': 242.0,\n"
        " 'projected_points_median': 446, 'projected_points_p10': 390,\n"
        " 'projected_points_p90': 490, 'races_in_sample': 11,\n"
        " 'measured_dnf_rate': 0.08}",
        notes=[
            "Two questions, kept apart on purpose. "
            "<code>title_scenarios</code> answers <em>can this still "
            "happen</em> — maximum points remaining is a fixed number, so that "
            "is arithmetic, not a forecast. "
            "<code>championship_projection</code> answers <em>how likely</em>. "
            "Printing one as the other is how a projection ends up implying "
            "somebody is eliminated when the maths says otherwise.",
            "A simulated finish is resampled from that driver's own results, "
            "not drawn from a curve around their average. The difference "
            "decides championships: alternating wins and retirements is a "
            "different proposition from finishing fourth every weekend, and "
            "the mean cannot tell them apart. Retirements fire at each "
            "driver's measured rate and sprints score on their own table.",
            "Every run re-draws the driver's level first, bootstrapping their "
            "results before playing the season against that version of them. "
            "Twelve races is a small sample, and treating it as settled is how "
            "a forecast becomes more confident than anyone should be.",
            "<code>f1verse.backtest_projection()</code> replays the model on "
            "finished seasons and buckets the record by claimed confidence. "
            "At round 12 of 2019-2025 it went 5/5 when it claimed 90%+, and "
            "both misses were seasons it had itself called near 55% — the two "
            "that ran to the final round.",
        ],
        related=["f1-race-json-one-call", "f1-undercut-analysis", "f1-mcp-server"],
    ),
    Page(
        "f1-tyre-degradation",
        "Measure F1 tyre degradation in Python",
        "How do I measure F1 tyre degradation from race data?",
        "Call <code>f1verse.stint_degradation(race)</code>. It returns seconds "
        "lost per lap for each stint, computed on fuel-normalised clean laps "
        "only, and reports how many laps each rate stands on.",
        '>>> f1verse.stint_degradation(race)[3]\n'
        "{'driver': 'NOR', 'stint': 2, 'compound': 'HARD', 'tyre_age_at_start': 0,\n"
        " 'clean_laps_used': 18, 'degradation_s_per_lap': 0.041}\n"
        '>>> f1verse.circuit_abrasion(race)\n'
        "{'factor': 1.4, 'verdict': 'abrasive', 'samples': 55}",
        notes=[
            "A car gets faster all race as it burns fuel, so raw lap times "
            "understate degradation on every stint. <code>fuel_normalised()</code> "
            "removes that trend before any rate is fitted — without it, a "
            "degradation number is mostly a fuel number.",
            "Pit, safety-car and traffic laps are excluded, and a stint with too "
            "few clean laps left returns "
            "<code>{'degradation_s_per_lap': None, 'reason': 'too few clean "
            "laps'}</code> rather than a rate fitted to noise. Every number "
            "carries its sample count.",
            "<code>f1verse.tyre_outlook(race)</code> projects the same rates "
            "forward to the point where a stint falls off its cliff.",
        ],
        related=["f1-undercut-analysis", "f1-race-json-one-call", "f1-results-final"],
    ),
    Page(
        "f1-deleted-lap-times",
        "Find F1 lap times deleted by the stewards",
        "How do I find F1 lap times that were deleted by the stewards?",
        "Call <code>f1verse.lap_deletions(messages)</code>, or the "
        "<code>f1_deleted_laps</code> tool. It returns every deletion race "
        "control announced — car, time, reason — and whether the deletion still "
        "stands after any reinstatement.",
        '>>> f1verse.call_tool("f1_deleted_laps",\n'
        '...     {"year": 2026, "round": 12, "session": "Qualifying"})["deletions"][0]\n'
        "{'car_number': 55, 'lap_time': '1:25.773',\n"
        "  'reason': 'TRACK LIMITS AT TURN 3 LAP 3', 'stands': True,\n"
        "  'date': '2026-08-22T14:04:59+00:00'}",
        notes=[
            "A reinstated lap is reported with the reversal visible rather than "
            "quietly dropped. The fact that a time was struck and then given "
            "back is part of the record, not noise to clean up.",
            "Check this before treating a fastest lap or a qualifying position "
            "as settled — a deletion changes a classification without the "
            "classification looking any different.",
        ],
        related=["f1-results-final", "f1-qualifying-gaps", "f1-detect-result-changes"],
    ),
    Page(
        "f1-live-timing-python",
        "Read the F1 live timing feed in Python",
        "How do I read the Formula 1 live timing feed in Python?",
        "Use <code>f1verse.sources.liveclient.LiveFeed</code>. It speaks the "
        "official SignalR feed over a WebSocket implemented in the standard "
        "library — no websocket package, no SignalR client, no browser.",
        'from f1verse.sources import liveclient\n\n'
        'with liveclient.LiveFeed() as feed:\n'
        '    for topic, patch, stamp in feed.messages():\n'
        '        ...\n\n'
        'liveclient.run("session-{n}.jsonl")   # record, rotate, reconnect',
        notes=[
            "Connecting takes three undocumented courtesies: the load balancer "
            "issues its affinity cookie only to a pre-flight request and rejects "
            "sockets arriving without it, the service expects the official "
            "application's user agent, and a subscription sent without an "
            "invocation id is accepted silently and never answered. All three "
            "are handled here so no caller has to rediscover them.",
            "Recordings carry a millisecond arrival stamp per frame, which is "
            "the difference between an archive and a screenshot — "
            "<code>replay()</code> can then run a session at true speed. "
            "Recordings are local working data; nothing is redistributed.",
            "The raw stream is not a lap table. "
            "<code>f1verse.sources.timing.laps_from_stream()</code> rebuilds "
            "honest laps from it, because arrival order lies: sector times land "
            "after the next lap has begun, and qualifying carries phantom lap "
            "times that are really the gap between two runs.",
        ],
        related=["f1-schedule-pipeline", "f1-results-final", "f1-mcp-server"],
    ),
]

MCP_PAGE = Page(
    "f1-mcp-server",
    "Formula 1 MCP server",
    "How do I give an AI agent access to Formula 1 data?",
    "Point any MCP client at <code>uvx --from f1verse f1verse-mcp</code>. There is no install "
    "step and no dependency tree: the server is standard library only, so it "
    "starts and answers <code>tools/list</code> in about 140 ms.",
    '{\n'
    '  "mcpServers": {\n'
    '    "f1verse": {"command": "uvx", "args": ["--from", "f1verse", "f1verse-mcp"]}\n'
    '  }\n'
    '}',
    notes=[
        "A catalogue a model can actually choose from, not eighty "
        "near-duplicates. The server tells the client to resolve vague "
        "references with "
        "<code>f1_season_status</code> first, and to check "
        "<code>f1_data_quality</code> before calling a fresh result final.",
        "For any other LLM pipeline, the library emits the same catalogue "
        "itself: <code>f1verse.tools()</code> for MCP-dialect schemas, "
        "<code>f1verse.tools(\"openai\")</code> for function-calling schemas, "
        "and <code>f1verse.call_tool(name, arguments)</code> to execute one. "
        "There is one catalogue behind both, so they cannot drift.",
        "Errors are written for the caller that has to fix them without "
        "reading this page: an unknown tool name lists the real ones, a "
        "missing argument names it, an unexpected argument names what is "
        "accepted.",
    ],
    related=["f1-race-json-one-call", "f1-results-final", "grounded-f1-summaries"],
)

ALL = [MCP_PAGE] + PAGES
BY_SLUG = {p.slug: p for p in ALL}

CSS = """
:root{--bg:#fbfbfa;--fg:#16181d;--dim:#5b6270;--line:#e4e4e6;--accent:#c8102e;
--code-bg:#f4f4f2}
@media (prefers-color-scheme:dark){
:root{--bg:#0f1115;--fg:#e7e9ee;--dim:#98a0b0;--line:#262a33;--accent:#ff4d63;
--code-bg:#161a21}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:16px/1.65 ui-sans-serif,-apple-system,"Segoe UI",Inter,system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
.wrap{max-width:46rem;margin:0 auto;padding:2.5rem 1.25rem 5rem}
a{color:inherit;text-decoration-color:var(--line);text-underline-offset:3px}
a:hover{text-decoration-color:var(--accent)}
header.top{display:flex;gap:1.25rem;align-items:baseline;flex-wrap:wrap;
padding-bottom:1.5rem;margin-bottom:2.5rem;border-bottom:1px solid var(--line)}
header.top .name{font-weight:650;letter-spacing:-.01em}
header.top nav{margin-left:auto;display:flex;gap:1rem;font-size:.875rem;
color:var(--dim)}
h1{font-size:1.9rem;line-height:1.25;letter-spacing:-.02em;margin:0 0 1rem}
h2{font-size:1.15rem;letter-spacing:-.01em;margin:2.75rem 0 .75rem}
.answer{font-size:1.125rem;line-height:1.6;margin:0 0 1.75rem}
p{margin:0 0 1rem}
em{color:var(--fg)}
code{font-family:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;
font-size:.9em;background:var(--code-bg);padding:.1em .35em;border-radius:3px}
pre{background:var(--code-bg);border:1px solid var(--line);border-radius:8px;
padding:1rem 1.1rem;overflow-x:auto;margin:0 0 1.75rem}
pre code{background:none;padding:0;font-size:.85rem;line-height:1.6}
.tag{display:inline-block;font-size:.7rem;letter-spacing:.08em;
text-transform:uppercase;color:var(--dim);border:1px solid var(--line);
border-radius:99px;padding:.15rem .6rem;margin-bottom:1.25rem}
ul.q{list-style:none;padding:0;margin:0}
ul.q li{border-bottom:1px solid var(--line)}
ul.q li:first-child{border-top:1px solid var(--line)}
ul.q a{display:block;padding:.9rem 0;text-decoration:none}
ul.q a:hover{color:var(--accent)}
ul.q .a{display:block;color:var(--dim);font-size:.875rem;margin-top:.15rem}
footer{margin-top:4rem;padding-top:1.5rem;border-top:1px solid var(--line);
color:var(--dim);font-size:.8125rem}
.note{color:var(--dim);font-size:.9375rem}
"""


def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def head(page: Page, description: str, jsonld: list) -> str:
    blocks = "\n".join(
        f'<script type="application/ld+json">{json.dumps(b)}</script>'
        for b in jsonld)
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(page.title)} · f1verse</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{page.url}">
<meta property="og:title" content="{html.escape(page.title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:url" content="{page.url}">
<meta property="og:type" content="article">
<meta name="twitter:card" content="summary">
<style>{CSS}</style>
{blocks}
</head><body><div class="wrap">
<header class="top">
  <span class="name"><a href="{SITE}/">f1verse</a></span>
  <nav>
    <a href="{SITE}/{MCP_PAGE.slug}/">MCP server</a>
    <a href="{REPO}">GitHub</a>
    <a href="https://pypi.org/project/f1verse/">PyPI</a>
  </nav>
</header>"""


FOOTER = f"""
<footer>
<p>f1verse {__version__} · Apache-2.0 · <a href="{REPO}">github.com/jinsim/f1verse</a>
· <a href="{SITE}/llms.txt">llms.txt</a></p>
<p>Unofficial fan project. Not affiliated with, endorsed by, or associated with
Formula 1, FIA, FOM, or any F1 team. F1, FORMULA 1 and related marks are
trademarks of Formula One Licensing BV. This site documents code only — no
timing data, media or images are bundled or redistributed; data is fetched by
the end user from publicly accessible endpoints.</p>
</footer>
</div></body></html>"""


def faq_entry(page: Page) -> dict:
    return {"@type": "Question", "name": page.question,
            "acceptedAnswer": {"@type": "Answer",
                               "text": strip_tags(page.answer)}}


def render_page(page: Page) -> str:
    description = strip_tags(page.answer)
    jsonld = [
        {"@context": "https://schema.org", "@type": "FAQPage",
         "url": page.url, "mainEntity": [faq_entry(page)]},
        {"@context": "https://schema.org", "@type": "BreadcrumbList",
         "itemListElement": [
             {"@type": "ListItem", "position": 1, "name": "f1verse",
              "item": f"{SITE}/"},
             {"@type": "ListItem", "position": 2, "name": page.title,
              "item": page.url}]},
    ]
    parts = [head(page, description, jsonld),
             '<span class="tag">f1verse · Python</span>',
             f"<h1>{html.escape(page.question)}</h1>",
             f'<p class="answer">{page.answer}</p>',
             f"<pre><code>{html.escape(page.code)}</code></pre>"]
    for note in page.notes:
        parts.append(f'<p class="note">{note}</p>')
    related = [BY_SLUG[s] for s in page.related if s in BY_SLUG]
    if related:
        parts.append("<h2>Related</h2><ul class='q'>")
        for rel in related:
            parts.append(f'<li><a href="{SITE}/{rel.slug}/">{html.escape(rel.question)}'
                         f'</a></li>')
        parts.append("</ul>")
    parts.append(FOOTER)
    return "\n".join(parts)


def render_index() -> str:
    index = Page("", "f1verse — the story layer for Formula 1 data",
                 "Formula 1 data with the domain rules already applied", "", "")
    description = (
        "Zero-dependency Python library and MCP server for Formula 1: lead "
        "changes, laps led, stints, race pace, and a publishable-or-not verdict "
        "on the data itself.")
    jsonld = [
        {"@context": "https://schema.org", "@type": "SoftwareSourceCode",
         "name": "f1verse", "description": TAGLINE, "url": f"{SITE}/",
         "codeRepository": REPO, "programmingLanguage": "Python",
         "runtimePlatform": "Python 3.9+", "version": __version__,
         "license": "https://www.gnu.org/licenses/agpl-3.0.html",
         "applicationCategory": "DeveloperApplication",
         "keywords": ("Formula 1, F1, motorsport, telemetry, race analysis, "
                      "MCP server, LLM tools, zero dependency")},
        {"@context": "https://schema.org", "@type": "FAQPage",
         "url": f"{SITE}/",
         "mainEntity": [faq_entry(p) for p in ALL]},
    ]
    tools = _tools.catalog("mcp")
    parts = [head(index, description, jsonld),
             "<h1>Formula 1 data with the domain rules already applied</h1>",
             '<p class="answer">f1verse answers <em>what happened in this '
             'race</em> — lead changes, laps led, the timeline, stints, race '
             'pace — and tells you whether the data is complete and final '
             'enough to publish. Zero dependencies, standard library only, '
             'seasons 2023 onward with records back to 1950.</p>',
             "<pre><code>" + html.escape(
                 'pip install f1verse\n\n'
                 '>>> import f1verse\n'
                 '>>> race = f1verse.load(2026, 12)\n'
                 '>>> race.laps_led()\n'
                 "{'ANT': 32, 'NOR': 31, 'HAM': 9}\n"
                 '>>> race.story()               # one call, whole race, plain JSON\n'
                 '>>> race.quality_report()      # is it safe to publish yet?')
             + "</code></pre>",
             "<h2>For agents</h2>",
             '<p>The bundled MCP server needs no install step and no '
             f'dependencies — see <a href="{SITE}/{MCP_PAGE.slug}/">the MCP '
             'server page</a>.</p>',
             "<pre><code>" + html.escape(
                 '{"mcpServers": {"f1verse": {"command": "uvx",\n'
                 '  "args": ["--from", "f1verse", "f1verse-mcp"]}}}') + "</code></pre>",
             f'<p class="note">{len(tools)} tools: ' +
             ", ".join(f"<code>{t['name']}</code>" for t in tools) + ".</p>",
             "<h2>Questions this answers</h2><ul class='q'>"]
    for page in ALL:
        parts.append(
            f'<li><a href="{SITE}/{page.slug}/">{html.escape(page.question)}'
            f'<span class="a">{strip_tags(page.answer)[:120]}…</span></a></li>')
    parts.append("</ul>")
    parts.append(FOOTER)
    return "\n".join(parts)


def render_llms_txt() -> str:
    return (ROOT / "llms.txt").read_text()


def render_llms_full() -> str:
    """One fetch, whole library — the shape an agent actually wants."""
    tools = _tools.catalog("mcp")
    out = [f"# f1verse {__version__} — complete reference for language models",
           "", f"> {TAGLINE} Source: {REPO} · Site: {SITE}/", "",
           "## Tool catalogue", "",
           "Available over MCP (`uvx --from f1verse f1verse-mcp`) and in-process via",
           "`f1verse.tools()` / `f1verse.call_tool(name, arguments)`.", ""]
    for tool in tools:
        required = ", ".join(tool["inputSchema"]["required"]) or "none"
        out += [f"### {tool['name']}", "", tool["description"], "",
                f"Required arguments: {required}", "",
                "```json", json.dumps(tool["inputSchema"], indent=2), "```", ""]
    out += ["## Questions and answers", ""]
    for page in ALL:
        out += [f"### {page.question}", "", strip_tags(page.answer), "",
                "```python", page.code, "```", ""]
        out += [strip_tags(n) for n in page.notes] + [""]
    out += ["## README", "", (ROOT / "README.md").read_text(),
            "", "## Repository map and invariants", "",
            (ROOT / "AGENTS.md").read_text()]
    return "\n".join(out)


def build(outdir: pathlib.Path) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / ".nojekyll").write_text("")
    (outdir / "index.html").write_text(render_index())
    for page in ALL:
        directory = outdir / page.slug
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "index.html").write_text(render_page(page))
    (outdir / "llms.txt").write_text(render_llms_txt())
    (outdir / "llms-full.txt").write_text(render_llms_full())
    (outdir / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\n"
        f"Sitemap: {SITE}/sitemap.xml\n")
    urls = "".join(f"<url><loc>{p.url}</loc></url>" for p in [
        Page("", "", "", "", "")] + ALL)
    (outdir / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f'{urls}</urlset>')
    print(f"built {len(ALL) + 1} pages into {outdir}")


if __name__ == "__main__":
    build(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "site"))
