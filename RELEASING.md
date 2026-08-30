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

## Every release

1. Choose the next semantic version and update only
   `src/f1verse/_version.py`. Build metadata, `f1verse.__version__`, and the
   HTTP user agent all read that one value.
2. Update user-facing documentation and commit the release.
3. Confirm the `test` workflow is green on `main`.
4. Create and push one annotated tag:

   ```bash
   git tag -a v0.9.1 -m "f1verse 0.9.1"
   git push origin v0.9.1
   ```

The tag workflow repeats the tests on Python 3.9 and 3.12, verifies that the
tag exactly matches `src/f1verse/_version.py`, builds both distributions, publishes to
PyPI through OIDC, and creates the matching GitHub Release. If any step fails,
PyPI publication does not run.

Published PyPI versions and release tags are immutable. Fixes therefore use a
new patch version rather than replacing an existing release.
