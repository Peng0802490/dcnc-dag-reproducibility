#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Profile the DynVMP bridge stage by stage inside one Python-2 process.

Run through tools/run_dynvmp_bridge.sh's environment.  Reports how much of the
measured 24 s per simulator slot is process startup and how much is the solve,
which decides whether a persistent-server bridge is worth building.
"""
from __future__ import print_function

import json
import sys
import time
from pathlib import Path

T0 = time.time()
from alib import datamodel  # noqa: F401
from vnep_approx.treewidth_model import DynVMPAlgorithm  # noqa: F401
IMPORT_S = time.time() - T0

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dynvmp_bridge as B


def main():
    path = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    payloads = [json.loads(l) for l in open(path) if l.strip()][:limit]

    tot = {"build": 0.0, "sp": 0.0, "td": 0.0, "solve": 0.0, "out": 0.0}
    td_cache = {}
    for p in payloads:
        t = time.time(); sub = B._build_substrate(p); req = B._build_request(p)
        algo = DynVMPAlgorithm(req, sub); tot["build"] += time.time() - t

        t = time.time(); sub.initialize_shortest_paths_costs(); tot["sp"] += time.time() - t

        key = json.dumps([sorted(f["id"] for f in p["dag"]["functions"]),
                          sorted((e["tail"], e["head"]) for e in p["dag"]["edges"])])
        t = time.time()
        if key in td_cache:
            td, td_method = td_cache[key]
        else:
            td, td_method = B._compute_td(req)
            td_cache[key] = (td, td_method)
        algo.tree_decomposition = td
        algo.tree_decomposition_arb = td.convert_to_arborescence()
        tot["td"] += time.time() - t

        t = time.time(); mapping = algo.compute_valid_mapping(); tot["solve"] += time.time() - t

        t = time.time()
        B._mapping_to_output(p, mapping, {"td_method": td_method, "td_width": td.width,
                                          "td_bags": len(td.nodes)})
        tot["out"] += time.time() - t

    n = len(payloads)
    print("\n--- per-call breakdown over %d payloads ---" % n)
    print("import (once)     : %8.3f s" % IMPORT_S)
    for k in ["build", "sp", "td", "solve", "out"]:
        print("%-18s: %8.4f s/call" % (k, tot[k] / n))
    per = sum(tot.values()) / n
    print("%-18s: %8.4f s/call" % ("TOTAL steady-state", per))
    print("\n8000-slot run: %.1f s (%.2f h) vs measured 195198 s for the one-shot bridge"
          % (per * 8000, per * 8000 / 3600.0))


if __name__ == "__main__":
    main()
