"""Shared fixtures."""
import pytest

import f1verse


@pytest.fixture(scope="session")
def race(tmp_path_factory):
    """The reference race, fetched once and cached for the whole run."""
    f1verse.enable_cache(str(tmp_path_factory.mktemp("cache")))
    return f1verse.load(2026, 12)
