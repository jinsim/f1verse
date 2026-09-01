# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""The public tree must remain portable and independent of local workspaces."""
import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIRS = ("src", "tests", "scripts", "examples")
PUBLIC_FILES = (
    "AGENTS.md", "CHANGELOG.md", "CONTRIBUTING.md", "NOTICE", "README.md",
    "RELEASING.md", "SECURITY.md", "llms.txt", "pyproject.toml", "server.json",
)
LOCAL_PATH_MARKERS = (
    "/" + "Users/",
    "\\" + "Users" + "\\",
    "/" + "home/",
)

# Typographic punctuation and accented names are deliberate; a run of Hangul,
# kana or CJK is a working note that escaped a scratch file.
LOCALISED_SCRIPT = re.compile(
    "[" + "\uac00-\ud7af\u1100-\u11ff\u3130-\u318f"
    "\u3040-\u30ff\u4e00-\u9fff" + "]")
TEXT_SUFFIXES = {".py", ".md", ".toml", ".json", ".yml", ".yaml", ".txt", ".cfg"}


def _public_files():
    for name in PUBLIC_DIRS:
        root = ROOT / name
        if root.exists():
            yield from (p for p in root.rglob("*")
                        if p.is_file() and "__pycache__" not in p.parts
                        and p.suffix != ".pyc")
    for name in PUBLIC_FILES:
        path = ROOT / name
        if path.exists():
            yield path


def test_public_tree_has_no_developer_machine_paths():
    leaked = {}
    for path in _public_files():
        text = path.read_text(errors="ignore")
        hits = [marker for marker in LOCAL_PATH_MARKERS if marker in text]
        if hits:
            leaked[str(path.relative_to(ROOT))] = hits
    assert not leaked, f"local workspace paths in public files: {leaked}"


def test_public_tree_contains_no_symlinks():
    links = []
    for name in PUBLIC_DIRS:
        root = ROOT / name
        if root.exists():
            links.extend(str(p.relative_to(ROOT)) for p in root.rglob("*")
                         if p.is_symlink())
    assert not links, f"public tree contains symlinks: {links}"


def test_public_tree_publishes_in_english():
    """Localised prose in the public tree is a note that escaped, not copy."""
    leaked = {}
    for path in _public_files():
        if path.suffix not in TEXT_SUFFIXES:
            continue
        hit = LOCALISED_SCRIPT.search(path.read_text(errors="ignore"))
        if hit:
            leaked[str(path.relative_to(ROOT))] = hit.group()
    assert not leaked, f"localised script in public files: {leaked}"


def test_src_imports_only_the_standard_library():
    """The zero-dependency rule is the whole install story, so it is checked
    on the syntax tree — a module reaching for a missing package would fail
    at import time, too late to report clearly.

    An import guarded by ``except ImportError`` is the documented way to let
    an optional value through and does not count against the rule.
    """
    outside = set()
    for path in sorted((ROOT / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded = {name
                   for node in ast.walk(tree)
                   if isinstance(node, ast.Try)
                   and any(isinstance(h.type, ast.Name)
                           and h.type.id == "ImportError" for h in node.handlers)
                   for inner in ast.walk(node)
                   if isinstance(inner, (ast.Import, ast.ImportFrom))
                   for name in ([a.name for a in inner.names]
                                if isinstance(inner, ast.Import)
                                else [inner.module or ""])}
        guarded = {n.split(".")[0] for n in guarded}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                outside |= {a.name.split(".")[0] for a in node.names} - guarded
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                head = node.module.split(".")[0]
                if head not in guarded:
                    outside.add(head)
    stray = sorted(n for n in outside
                   if n not in sys.stdlib_module_names and n != "f1verse")
    assert not stray, f"src/ imports outside the standard library: {stray}"


def test_localised_detector_knows_script_from_typography():
    """Written with escapes so this file stays ASCII while still proving the
    detector separates a stray note from deliberate English typography."""
    for localised in ("\uc2a4\ud2f4\ud2b8", "\u30bf\u30a4\u30e4", "\u8f6e\u80ce"):
        assert LOCALISED_SCRIPT.search(localised)
    for allowed in ("pace \u2014 corrected", "lap \u2192 sector",
                    "Sergio P\u00e9rez", "N\u00fcrburgring", "\u00b10.2 s"):
        assert not LOCALISED_SCRIPT.search(allowed), allowed
