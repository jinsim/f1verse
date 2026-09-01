#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Pre-release gate — does this commit deserve the version it claims?

Three questions, in the order a reviewer would ask them. Tree hygiene —
localised prose, developer paths, stray dependencies, symlinks — is asserted
by ``tests/test_public_boundary.py`` and runs in the same CI, so it is not
repeated here.

1. **Do the version numbers agree?** `_version.py`, both `server.json`
   fields, and the tag being released.
2. **Does the version bump match what actually changed?** The public
   surface (exports, `Race` methods, MCP tools) is read from the last
   release tag with `ast` — no install, no network — and diffed against
   this working tree. Removing anything demands a major bump; adding
   demands at least a minor one; an unchanged surface demands nothing, so
   documentation and internals can land without touching the version.
3. **Was the change written down?** A surface change has to appear in
   `CHANGELOG.md` under this version, by name.

Run it with no arguments to check the working tree, or `--tag v0.14.0`
to also assert the tag agrees. Exit status is 0 only if every gate
passes; each failure prints what to do about it.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent



def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout



# --- gate 1: version agreement ----------------------------------------

def declared_version() -> str:
    text = (ROOT / "src" / "f1verse" / "_version.py").read_text()
    return re.search(r'__version__\s*=\s*"([^"]+)"', text).group(1)


def gate_versions(failures: list, tag: str | None) -> str:
    version = declared_version()
    manifest = json.loads((ROOT / "server.json").read_text())
    found = {manifest.get("version")} | {
        p.get("version") for p in manifest.get("packages", [])}
    if found != {version}:
        failures.append(
            f"server.json declares {sorted(v for v in found if v)} but "
            f"_version.py says {version}")
    if tag and tag.lstrip("v") != version:
        failures.append(f"tag {tag} does not match _version.py {version}")
    return version


# --- gate 2: surface vs the last release ------------------------------

def _names_in(tree: ast.AST, target: str) -> list:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == target for t in node.targets):
            return [e.value for e in node.value.elts
                    if isinstance(e, ast.Constant)]
    return []


def _tool_names(tree: ast.AST) -> list:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "_SPECS" for t in node.targets):
            return [v.value for spec in node.value.elts
                    for k, v in zip(spec.keys, spec.values)
                    if getattr(k, "value", None) == "name"]
    return []


def _race_methods(tree: ast.AST) -> list:
    return [n.name for cls in ast.walk(tree)
            if isinstance(cls, ast.ClassDef) and cls.name == "Race"
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]


def _surface(read) -> dict:
    return {
        "exports": set(_names_in(ast.parse(read("src/f1verse/__init__.py")),
                                 "__all__")),
        "tools": set(_tool_names(ast.parse(read("src/f1verse/_tools.py")))),
        "race": set(_race_methods(ast.parse(read("src/f1verse/race.py")))),
    }


def last_tag() -> str | None:
    tags = [t for t in _git("tag", "--sort=-v:refname").splitlines() if t]
    return tags[0] if tags else None


def gate_surface(failures: list, version: str) -> dict:
    previous = last_tag()
    if not previous:
        return {}
    now = _surface(lambda p: (ROOT / p).read_text(encoding="utf-8"))
    was = _surface(lambda p: _git("show", f"{previous}:{p}"))

    removed = {k: sorted(was[k] - now[k]) for k in now}
    added = {k: sorted(now[k] - was[k]) for k in now}
    any_removed = any(removed.values())
    any_added = any(added.values())

    # Nothing moved on the public surface means nothing is *required* — a
    # docs-only or internals-only change is free to keep the version it has.
    need = "major" if any_removed else "minor" if any_added else "none"
    old = [int(x) for x in previous.lstrip("v").split(".")]
    new = [int(x) for x in version.split(".")]
    got = ("major" if new[0] > old[0] else "minor" if new[1] > old[1]
           else "patch" if new[2] > old[2] else "none")

    rank = {"none": 0, "patch": 1, "minor": 2, "major": 3}
    if rank[got] < rank[need]:
        detail = "; ".join(
            f"{kind} {k}: {', '.join(v)}"
            for kind, group in (("removed", removed), ("added", added))
            for k, v in group.items() if v)
        failures.append(
            f"{version} is a {got} bump over {previous} but the surface change"
            f" needs {need} ({detail})")
    return {"previous": previous, "added": added, "removed": removed,
            "required": need, "declared": got}


# --- gate 3: the change is written down -------------------------------

def gate_changelog(failures: list, version: str, diff: dict) -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if version not in text:
        failures.append(f"CHANGELOG.md has no entry for {version}")
        return
    # Cut at the next *version* heading, not the next heading of any depth —
    # an entry's own "### Fixed" subsections are part of the entry.
    section = re.split(r"\n## ", text.split(version, 1)[1])[0]
    changed = [n for group in (diff.get("added", {}), diff.get("removed", {}))
               for names in group.values() for n in names]
    unmentioned = [n for n in changed if n not in section]
    if unmentioned:
        failures.append(
            f"CHANGELOG.md {version} does not mention: "
            f"{', '.join(sorted(unmentioned)[:8])}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", help="tag being released, e.g. v0.14.0")
    args = ap.parse_args()

    failures: list = []
    version = gate_versions(failures, args.tag)
    diff = gate_surface(failures, version)
    gate_changelog(failures, version, diff)

    if diff:
        moved = sum(len(v) for g in ("added", "removed") for v in diff[g].values())
        print(f"{diff['previous']} → {version} · surface changes: {moved}"
              f" · needs {diff['required']}, declared {diff['declared']}")
    if failures:
        print(f"\n{len(failures)} problem(s):", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("release check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
