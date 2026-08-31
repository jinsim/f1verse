# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""JSON-safe conversion — every public f1verse output passes through here.

Values arriving from analysis code may be numpy scalars or pandas
timestamps, which ``json.dumps`` rejects; this normalises them to plain
Python. Both libraries are optional and detected at import time.
"""
import datetime
import math

try:
    import numpy as _np
except ImportError:          # zero-dep native install
    _np = None
try:
    import pandas as _pd
except ImportError:
    _pd = None


def jsonsafe(obj):
    """Recursively convert *obj* to plain JSON-serializable Python types."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if _np is not None and isinstance(obj, _np.integer):
        return int(obj)
    if isinstance(obj, int):
        return obj
    if (_np is not None and isinstance(obj, _np.floating)) or isinstance(obj, float):
        f = float(obj)
        return None if math.isnan(f) else f
    if isinstance(obj, datetime.timedelta):
        return obj.total_seconds()
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if _pd is not None:
        if isinstance(obj, _pd.Timedelta):
            return None if obj is _pd.NaT else obj.total_seconds()
        if isinstance(obj, _pd.Timestamp):
            return obj.isoformat()
        if obj is _pd.NaT:
            return None
    if isinstance(obj, dict):
        return {str(k): jsonsafe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonsafe(v) for v in obj]
    if _np is not None and isinstance(obj, _np.ndarray):
        return [jsonsafe(v) for v in obj.tolist()]
    if _pd is not None and isinstance(obj, _pd.Series):
        return [jsonsafe(v) for v in obj.tolist()]
    if _pd is not None and _pd.isna(obj):
        return None
    return str(obj)
