# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""The release gate itself — the checks that decide whether a version ships."""
import ast
import importlib.util
import pathlib

_SPEC = importlib.util.spec_from_file_location(
    "release_check",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "release_check.py")
rc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rc)



def test_surface_is_read_from_source_without_importing():
    """The diff reads a released tag's files, which cannot be imported —
    so the extraction has to work on the syntax tree alone."""
    exports = rc._names_in(
        ast.parse('__all__ = ["load", "brief"]\n'), "__all__")
    assert exports == ["load", "brief"]
    tools = rc._tool_names(ast.parse(
        '_SPECS = [{"name": "f1_race_story", "summary": "x"}]\n'))
    assert tools == ["f1_race_story"]
    methods = rc._race_methods(ast.parse(
        "class Race:\n    def story(self): pass\n    def _hidden(self): pass\n"))
    assert methods == ["story"]


def test_changelog_section_covers_its_own_subsections(tmp_path, monkeypatch):
    """An entry's `### Fixed` subsections belong to that entry — slicing at
    any heading depth would hide most of what a release documented."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n## 0.14.0\n\n### Circuits\n\n- adds `circuit_facts`\n"
        "\n### Fixed\n\n- mends `fia_documents`\n\n## 0.13.1\n\n- older\n")
    monkeypatch.setattr(rc, "ROOT", tmp_path)
    failures = []
    rc.gate_changelog(failures, "0.14.0",
                      {"added": {"exports": ["circuit_facts"]},
                       "removed": {"exports": ["fia_documents"]}})
    assert failures == []

    # and a name that genuinely is not written down still fails
    failures = []
    rc.gate_changelog(failures, "0.14.0",
                      {"added": {"exports": ["undocumented_name"]},
                       "removed": {}})
    assert failures and "undocumented_name" in failures[0]
