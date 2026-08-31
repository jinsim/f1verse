# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

from importlib.metadata import version

import f1verse


def test_runtime_version_matches_installed_package_metadata():
    assert f1verse.__version__ == version("f1verse")
