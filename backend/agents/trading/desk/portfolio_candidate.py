"""A predeclared correlation cap for forward research, never order execution."""

import numpy as np

LOOKBACK = 60
MIN_OBSERVATIONS = 40
CORRELATION = 0.8
CLUSTER_CAP = 0.30
VERSION = "correlation-cluster-cap/1"


# Reduce overlapping long exposures without redistributing the released cash.
def calculate(panel, weights):
    names = sorted(name for name, weight in weights.items() if weight > 0)
    result = {
        "version": VERSION,
        "status": "unavailable",
        "clusters": [],
        "targets": None,
    }
    if not names:
        return {**result, "status": "available", "targets": dict(weights)}
    values = panel.log_returns()[-LOOKBACK:, [panel.index(name) for name in names]]
    values = values[np.isfinite(values).all(axis=1)]
    if len(values) < MIN_OBSERVATIONS or np.any(values.std(axis=0) <= 0):
        return {**result, "reason": "Insufficient common return history"}
    correlation = (
        np.atleast_2d(np.corrcoef(values, rowvar=False))
        if len(names) > 1
        else np.ones((1, 1))
    )
    remaining = set(range(len(names)))
    targets = dict(weights)
    clusters = []
    while remaining:
        group = {min(remaining)}
        while True:
            connected = {
                j
                for j in remaining
                if any(correlation[i, j] >= CORRELATION for i in group)
            }
            if connected <= group:
                break
            group |= connected
        remaining -= group
        members = [names[i] for i in sorted(group)]
        gross = sum(weights[name] for name in members)
        scale = min(1.0, CLUSTER_CAP / gross)
        for name in members:
            targets[name] *= scale
        clusters.append({"names": members, "before": gross, "after": gross * scale})
    return {
        **result,
        "status": "available",
        "targets": targets,
        "clusters": clusters,
        "observations": len(values),
        "correlation_threshold": CORRELATION,
        "cluster_cap": CLUSTER_CAP,
    }
