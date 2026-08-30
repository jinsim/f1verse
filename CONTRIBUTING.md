# Contributing

Thanks for looking. This is a small library with a few rules that matter
more than style, so start here.

## Before you write code

Read [AGENTS.md](AGENTS.md). It is the map of the repository and it lists
the invariants — the things a change must not break. Two of them catch
most first pull requests:

1. **Zero dependencies.** Standard library only, in the library and in the
   MCP server. If a third-party value could reach `jsonsafe`, guard the
   import so the module still loads without it.
2. **Domain rules are defaults, not options.** Race pace excludes pit,
   safety-car and virtual-safety-car laps. Lapped cars read `+1 LAP`.
   Undercut detection excludes neutralised laps. Correctness is not opt-in.

## Running the tests

```bash
python -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q
```

The suite fetches one reference race once and caches it for the run, so the
first run needs a network and takes about a minute. The agent-surface tests
(`tests/test_tools.py`, `tests/test_mcp.py`) are offline and finish
instantly — a model asking "what can this do?" should never pay for a fetch.

## Adding a tool to the agent surface

`src/f1verse/_tools.py` is the only definition of what an agent can call.
A new tool needs a `_SPECS` entry and a `_HANDLERS` entry; the tests fail if
they do not match. Write the description for a model choosing between eight
options, and write the errors for a caller that has to recover from them
without reading the docs.

## Documentation

The site at <https://jinsim.github.io/f1verse/> is generated, never
committed:

```bash
python scripts/build_docs.py && python -m http.server -d site 8000
```

Each page answers one question and leads with the answer.

## Data

No timing data, media or images are ever committed. Sources are fetched at
runtime by the end user. Team radio and FIA documents are returned as URLs.

## Pull requests

Small and focused, with a test that would have failed before. Describe what
the change makes true, not what files it touches.
