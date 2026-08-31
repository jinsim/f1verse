# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""The public tree must remain portable and independent of local workspaces."""
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
