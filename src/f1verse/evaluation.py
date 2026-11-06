# SPDX-License-Identifier: Apache-2.0
# Copyright (C) 2026 jinsim <https://github.com/jinsim>

"""Proper scores for race/title forecasts, separate from model fitting."""
import math

from ._evidence import evidence
from ._json import jsonsafe


def forecast_scores(cases: list) -> dict:
    """Score categorical forecasts against known outcomes.

    Each case needs ``probabilities`` (label -> probability) and ``actual``.
    Cases must be held out in time by the caller. Scores do not prove that
    they were issued before the outcome; replayed forecasts say so.
    Multiclass Brier is the sum, not the mean, over categories.
    """
    rows, skipped, buckets = [], [], {i: [] for i in range(10)}
    for i, case in enumerate(cases):
        probabilities, actual = case.get("probabilities"), case.get("actual")
        if not isinstance(probabilities, dict) or not probabilities:
            skipped.append({"index": i, "reason": "missing probabilities"})
            continue
        values = list(probabilities.values())
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or not 0 <= v <= 1 for v in values):
            raise ValueError(f"case {i}: probabilities must be finite values in [0, 1]")
        if abs(sum(values) - 1) > 0.001:
            raise ValueError(f"case {i}: probabilities must sum to 1")
        if actual not in probabilities:
            skipped.append({"index": i, "reason": "actual outcome not modelled"})
            continue
        # Remove only rounding drift (championship output rounds to 4 dp).
        total = sum(values)
        ps = {k: v / total for k, v in probabilities.items()}
        brier = sum((p - (k == actual)) ** 2 for k, p in ps.items())
        loss = -math.log(max(ps[actual], 1e-15))
        top = max(ps, key=ps.get)
        buckets[min(int(ps[top] * 10), 9)].append((ps[top], int(top == actual)))
        rows.append({"index": i, "brier": brier, "log_loss": loss,
                     "correct": top == actual})
    n = len(rows)
    return jsonsafe({"cases_scored": n, "skipped": skipped,
        "brier": sum(r["brier"] for r in rows) / n if n else None,
        "log_loss": sum(r["log_loss"] for r in rows) / n if n else None,
        "accuracy": sum(r["correct"] for r in rows) / n if n else None,
        "calibration_scope": "top-label confidence per forecast case",
        "calibration": [{"from": i / 10, "to": (i + 1) / 10, "n": len(v),
                         "mean_probability": sum(p for p, _ in v) / len(v),
                         "observed_rate": sum(y for _, y in v) / len(v)}
                        for i, v in buckets.items() if v],
        "evidence": evidence("multiclass_proper_scores", cases,
            sample_unit="forecast case; repeated forecasts may be dependent", samples=n,
            kind="evaluation", assumptions=["caller supplies time-held-out cases",
                "log loss clipped at probability 1e-15", "sum-over-labels Brier convention"])})
