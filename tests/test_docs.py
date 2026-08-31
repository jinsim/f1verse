"""The published surfaces: the site generator and the registry manifest.

These are the parts a reader — human or model — sees before any code runs,
and nothing else fails when they go stale.
"""
import json
import pathlib
import re
import sys

import pytest

import f1verse

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_docs                                              # noqa: E402


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    build_docs.build(out)
    return out


def test_server_json_tracks_the_package_version():
    """A manifest advertising a version PyPI does not have is a dead entry."""
    manifest = json.loads((ROOT / "server.json").read_text())
    assert manifest["version"] == f1verse.__version__
    package, = manifest["packages"]
    assert package["identifier"] == "f1verse"
    assert package["version"] == f1verse.__version__
    assert package["transport"]["type"] == "stdio"


def test_readme_carries_the_registry_ownership_marker():
    """The registry proves package ownership through the README PyPI serves.

    A published README cannot be edited, so a missing marker is only fixable
    by cutting another release — worth failing here instead.
    """
    manifest = json.loads((ROOT / "server.json").read_text())
    readme = (ROOT / "README.md").read_text()
    assert f"mcp-name: {manifest['name']}" in readme


def test_server_json_description_fits_the_registry_limit():
    """The registry rejects a publish over 100 characters, at release time."""
    manifest = json.loads((ROOT / "server.json").read_text())
    assert len(manifest["description"]) <= 100


def test_every_page_leads_with_its_answer():
    for page in build_docs.ALL:
        assert page.question.endswith("?"), page.slug
        assert page.answer and page.code, page.slug
        assert len(build_docs.strip_tags(page.answer)) < 400, page.slug


def test_related_links_all_resolve():
    for page in build_docs.ALL:
        for slug in page.related:
            assert slug in build_docs.BY_SLUG, f"{page.slug} -> {slug}"


def test_pages_carry_parseable_structured_data(site):
    pages = sorted(site.rglob("index.html"))
    assert len(pages) == len(build_docs.ALL) + 1
    for path in pages:
        blocks = re.findall(
            r'<script type="application/ld\+json">(.*?)</script>',
            path.read_text(), re.S)
        assert blocks, path
        types = {json.loads(b)["@type"] for b in blocks}
        assert "FAQPage" in types or "SoftwareSourceCode" in types


def test_llms_full_carries_the_whole_tool_catalogue(site):
    text = (site / "llms-full.txt").read_text()
    for name in f1verse._tools.NAMES:
        assert name in text


def test_site_advertises_the_working_uvx_invocation(site):
    """`uvx f1verse-mcp` would resolve a package that does not exist."""
    for path in list(site.rglob("*.html")) + [site / "llms-full.txt"]:
        text = path.read_text()
        for hit in re.findall(r"uvx[^<\n]{0,60}", text):
            if "f1verse-mcp" in hit:
                assert "--from" in hit and "f1verse" in hit, f"{path}: {hit}"
