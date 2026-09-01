# Releasing to PyPI

Publishing is tag-driven through GitHub Actions and PyPI Trusted Publishing.
No API token is stored in GitHub.

## One-time setup

1. Keep the GitHub environment named `pypi`.
2. On PyPI, add a pending trusted publisher with:
   - PyPI project: `f1verse`
   - GitHub owner: `jinsim`
   - Repository: `f1verse`
   - Workflow: `publish.yml`
   - Environment: `pypi`

## Deciding the version

Run the gate before choosing — it reads the last release tag and tells you
what the change actually requires:

```bash
python scripts/release_check.py
```

| What moved on the public surface | Required bump |
|---|---|
| An export, `Race` method or MCP tool was **removed or renamed** | major |
| Anything was **added** | minor |
| Nothing — docs, internals, fixes | patch, or leave the version alone |

The surface is read from the tag with `ast`, so this needs no install and no
network. Declaring a smaller bump than the change requires is an error, not a
warning: a consumer pinned to `~=0.13` must never silently lose a name.

The same script also refuses a tree that carries localised working notes,
absolute developer paths, unguarded third-party imports under `src/`, or a
surface change that `CHANGELOG.md` does not mention by name. It runs on every
pull request and again on the tag, where `publish.yml` waits on it — PyPI
versions are immutable, so the gate sits *before* publication rather than
after.

## Every release

1. Choose the next semantic version and update
   `src/f1verse/_version.py` **and the two `version` fields in
   `server.json`**. Build metadata, `f1verse.__version__` and the HTTP user
   agent all read `_version.py`; the MCP registry manifest cannot read it,
   so `tests/test_docs.py` fails the moment the two disagree.
2. Update user-facing documentation and commit the release.
3. Confirm the `test` and `release-check` workflows are green on `main`.
4. Create and push one annotated tag:

   ```bash
   git tag -a v0.9.1 -m "f1verse 0.9.1"
   git push origin v0.9.1
   ```

The tag workflow repeats the tests on Python 3.9 and 3.12, verifies that the
tag exactly matches `src/f1verse/_version.py`, builds both distributions, publishes to
PyPI through OIDC, and creates the matching GitHub Release. If any step fails,
PyPI publication does not run.

`mcp-registry.yml` then runs on its own, updating the listing in the official
MCP registry — also through OIDC, also with nothing stored. It waits for the
publish workflow to succeed, because a registry entry pointing at a version
PyPI cannot serve is worse than no entry. There is nothing to do by hand.

Published PyPI versions and release tags are immutable. Fixes therefore use a
new patch version rather than replacing an existing release.
