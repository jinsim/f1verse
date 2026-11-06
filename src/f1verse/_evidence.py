# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Small, deterministic lineage records for derived answers."""
import hashlib
import json

from ._json import jsonsafe
from ._version import __version__


def digest(value):
    return hashlib.sha256(json.dumps(jsonsafe(value), sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def evidence(method, inputs, *, sample_unit, samples, assumptions=(),
             exclusions=(), uncertainty=None, kind="estimate"):
    record = {"method": method, "method_version": 1,
              "library_version": __version__, "input_sha256": digest(inputs),
              "kind": kind, "sample_unit": sample_unit, "samples": samples,
              "assumptions": list(assumptions), "exclusions": list(exclusions),
              "uncertainty": uncertainty or {"kind": "not_estimated"}}
    record["run_id"] = digest(record)
    return jsonsafe(record)
