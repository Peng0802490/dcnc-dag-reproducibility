#!/usr/bin/env python3
"""Broad pilot: bracket every policy's knee on every candidate scenario.

Coarse geometric rate grid, short horizon, one seed.  The point is only to find
where each curve turns, so that the final campaign can put a dense grid around
each knee instead of stopping while the completion ratio is still 0.99 --- which
is what left CTS flat in Fig.3(b) and Randomized with three points in Fig.4.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "results" / "sweeps"
OUT.mkdir(exist_ok=True)

SCENARIOS = [
    # Fig.3 / Fig.5 driving task (configs unchanged: Fig.3(a) is already accepted)
    ("driving_milan", "config_driving_Milan.json"),
    ("driving_random", "config_driving_Random.json"),
    # Fig.4 candidates: one common random-DAG set across all four topologies
    ("r6_milan", "config_random6_Milan.json"),
    ("r6_random", "config_random6_Random.json"),
    ("r6_roofnet", "config_random6_Roofnet38_cap210.json"),
    ("r6_flocklab", "config_random6_FlockLab_cap210.json"),
    ("r5_milan", "config_random5_Milan.json"),
    ("r5_random", "config_random5_Random.json"),
    ("r5_roofnet", "config_random5_Roofnet38_cap210.json"),
    ("r5_flocklab", "config_random5_FlockLab_cap210.json"),
    # keep the un-rescaled dense topologies for comparison
    ("r6_roofnet_cap1", "config_random6_Roofnet38.json"),
    ("r6_flocklab_cap1", "config_random6_FlockLab.json"),
]

POLICIES = [("DCNC-DAG", "exact_dp"), ("DCNC-DAG", "greedy"), ("CTS", "cts"), ("Random", "random")]

RATES = [0.01, 0.02, 0.04, 0.08, 0.15, 0.25, 0.4, 0.6, 0.9, 1.3, 1.8, 2.5]

jobs = []
for case, config in SCENARIOS:
    for policy, solver in POLICIES:
        for r in RATES:
            jobs.append(dict(case=case, config=config, policy=policy, solver=solver,
                             fixed_k=1, slots=4000, seed=1, rate=r))

(OUT / "pilot.json").write_text(json.dumps(jobs, indent=1))
print("%d jobs -> %s" % (len(jobs), OUT / "pilot.json"))
