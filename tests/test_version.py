from importlib.metadata import version

import f1verse


def test_runtime_version_matches_installed_package_metadata():
    assert f1verse.__version__ == version("f1verse")
