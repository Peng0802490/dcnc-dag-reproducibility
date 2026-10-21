#!/usr/bin/env python3
"""Give each service function its own set of qualified compute nodes.

Every shipped config lets all functions of a DAG run on one common pool of
compute nodes (distinct_sets=1 in all of them).  Under that model the placement
problem nearly decomposes across functions, so the topological-order greedy of
DCNC-DAG-H is close to optimal and its curve sits on top of DCNC-DAG's.

Function-specific qualification is the standard assumption in service-function
chaining -- a function runs only where its image, licence, accelerator or
resident data is available -- and it couples the per-function decisions, which
is what an exact minimum-cost mapping can exploit and a myopic greedy cannot.

The subsets are drawn once with a fixed seed and stored in the config, so they
are part of the instance and identical for every policy compared on it.
"""
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "inputs" / "configs"


def variant(src_cfg: str, frac: float, seed: int, suffix: str) -> str:
    cfg = json.loads((ROOT / src_cfg).read_text(encoding="utf-8"))
    rng = random.Random(seed)
    report = []
    for sdag in cfg["service_dags"]:
        allowed = sdag.get("allowed") or {}
        if not allowed:
            continue
        pool = sorted({u for v in allowed.values() for u in v}, key=lambda x: (len(x), x))
        k = max(3, int(math.ceil(frac * len(pool))))
        new = {}
        for func in sorted(allowed):
            new[func] = sorted(rng.sample(pool, k), key=lambda x: (len(x), x))
        # every node in the pool must stay usable by someone, otherwise the
        # effective network silently shrinks and the comparison drifts
        missing = set(pool) - {u for v in new.values() for u in v}
        for u in sorted(missing):
            f = rng.choice(sorted(new))
            new[f] = sorted(set(new[f]) | {u}, key=lambda x: (len(x), x))
        sdag["allowed"] = new
        report.append("%s:|pool|=%d,k=%d" % (sdag["name"], len(pool), k))
    dst = src_cfg.replace(".json", "_%s.json" % suffix)
    (ROOT / dst).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print("  %-44s -> %-46s %s" % (src_cfg, dst, " ".join(report)))
    return dst


def main() -> None:
    base = [
        "config_driving_Milan.json",
        "config_driving_Random.json",
        "config_random6_Milan.json",
        "config_random6_Random.json",
        "config_random6_Roofnet38_cap210.json",
        "config_random6_FlockLab_cap210.json",
    ]
    for frac, suffix in [(0.45, "q45"), (0.65, "q65")]:
        print("fraction %.2f -> suffix %s" % (frac, suffix))
        for i, cfg in enumerate(base):
            variant(cfg, frac, 20260719 + 17 * i, suffix)


if __name__ == "__main__":
    main()
