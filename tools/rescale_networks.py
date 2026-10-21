#!/usr/bin/env python3
"""Give RoofNet38 and FlockLab the same capacity model as Milan and the random
topology: node and directed-arc capacities drawn uniformly from {2,...,10}.

Section VII-A of the paper already states this model for all four topologies,
but inputs/topologies/Roofnet38_emulated.json and inputs/topologies/FlockLab.json ship with every
capacity fixed at 1.0.  That is why those two subfigures are compressed into a
tiny rate range and why the DCNC curves die almost immediately.  Only the
capacities change; node set, arc set and the dynamic/p_on flags are untouched,
so the measured graph structure the topologies contribute is preserved.

Writes <name>_cap210.json next to the original and derived configs that use it.
"""
import copy
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "inputs" / "configs"
SEED = 20260719


def rescale(src_name: str, dst_name: str, seed: int) -> None:
    src = ROOT.parent / "topologies" / src_name
    dst = ROOT.parent / "topologies" / dst_name
    net = json.loads(src.read_text(encoding="utf-8"))
    rng = random.Random(seed)

    for n in net["nodes"]:
        n["capacity"] = rng.randint(2, 10)
    for e in net["edges"]:
        e["capacity"] = rng.randint(2, 10)

    net["network_id"] = str(net.get("network_id", dst_name)) + "-cap210"
    net.setdefault("metadata", {})["capacity_model"] = (
        "node and directed-arc capacities i.i.d. uniform on {2,...,10}, seed %d" % seed
    )
    dst.write_text(json.dumps(net, indent=2, ensure_ascii=False), encoding="utf-8")

    ncap = [n["capacity"] for n in net["nodes"]]
    ecap = [e["capacity"] for e in net["edges"]]
    dyn = sum(1 for e in net["edges"] if e.get("dynamic"))
    print("%-28s -> %-30s nodes=%d edges=%d dynamic=%d nodecap=%d..%d edgecap=%d..%d"
          % (src_name, dst_name, len(net["nodes"]), len(net["edges"]), dyn,
             min(ncap), max(ncap), min(ecap), max(ecap)))


def derive_config(src_cfg: str, dst_cfg: str, new_net: str) -> None:
    src = ROOT / src_cfg
    cfg = json.loads(src.read_text(encoding="utf-8"))
    cfg = copy.deepcopy(cfg)
    cfg["network"]["file"] = "../topologies/" + new_net
    (ROOT / dst_cfg).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print("   config %-42s -> %s" % (src_cfg, dst_cfg))


def main() -> None:
    rescale("Roofnet38_emulated.json", "Roofnet38_emulated_cap210.json", SEED)
    rescale("FlockLab.json", "FlockLab_cap210.json", SEED + 1)
    for dagset in ["random3", "random4", "random5", "random6", "driving"]:
        for topo, newnet in [("Roofnet38", "Roofnet38_emulated_cap210.json"),
                             ("FlockLab", "FlockLab_cap210.json")]:
            src = "config_%s_%s.json" % (dagset, topo)
            if not (ROOT / src).exists():
                continue
            derive_config(src, "config_%s_%s_cap210.json" % (dagset, topo), newnet)


if __name__ == "__main__":
    main()
