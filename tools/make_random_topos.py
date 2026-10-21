#!/usr/bin/env python3
"""Build random topologies with real path diversity.

The shipped Network/Random.json is a 50-node graph with 50 undirected links,
i.e. a spanning tree plus one edge (average degree 2, diameter 12).  With
essentially one route between any pair, the choice of a valid mapping barely
matters, which is why DCNC-DAG and DCNC-DAG-H coincide on Fig.3(b).

Each variant keeps 50 nodes and the same capacity model as Milan (node and
directed-arc capacities i.i.d. uniform on {2,...,10}) and the same 12 dynamic
ingress-adjacent arcs used by the existing random-topology experiments, so the
only thing that changes is edge density.
"""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "legacy_inputs"
BASE = json.loads((ROOT / "Network" / "Random.json").read_text(encoding="utf-8"))
NODES = [str(n["id"]) for n in BASE["nodes"]]
DYNAMIC = {("31", "7"), ("7", "31"), ("35", "3"), ("3", "35"), ("40", "7"), ("7", "40"),
           ("18", "30"), ("30", "18"), ("20", "28"), ("28", "20"), ("5", "46"), ("46", "5")}


def build(n_undirected: int, seed: int, name: str) -> None:
    rng = random.Random(seed)
    # random spanning tree first so the graph is connected by construction
    order = NODES[:]
    rng.shuffle(order)
    undirected = set()
    for i in range(1, len(order)):
        u, v = order[i], order[rng.randrange(i)]
        undirected.add((u, v) if u < v else (v, u))
    # then fill up to the target density
    while len(undirected) < n_undirected:
        u, v = rng.sample(NODES, 2)
        undirected.add((u, v) if u < v else (v, u))
    # keep the dynamic arcs present so the wireless model is unchanged
    for (u, v) in DYNAMIC:
        undirected.add((u, v) if u < v else (v, u))

    nodes = [{"id": u, "role": "COMPUTE", "capacity": rng.randint(2, 10)} for u in NODES]
    edges = []
    for (u, v) in sorted(undirected):
        edges.append({"from": u, "to": v, "capacity": rng.randint(2, 10)})
        edges.append({"from": v, "to": u, "capacity": rng.randint(2, 10)})

    deg = {u: 0 for u in NODES}
    for (u, v) in undirected:
        deg[u] += 1
        deg[v] += 1
    net = {
        "network_id": name,
        "version": "2026-07-19",
        "description": "random connected topology, %d nodes, %d undirected links" % (len(NODES), len(undirected)),
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "generator": "random spanning tree + uniform extra edges, seed %d" % seed,
            "capacity_model": "node and directed-arc capacities i.i.d. uniform on {2,...,10}",
            "avg_degree": round(2.0 * len(undirected) / len(NODES), 2),
        },
    }
    (ROOT / "Network" / (name + ".json")).write_text(json.dumps(net, indent=2), encoding="utf-8")
    print("%-22s undirected=%-4d arcs=%-4d avg_deg=%.2f min_deg=%d"
          % (name, len(undirected), len(edges), 2.0 * len(undirected) / len(NODES), min(deg.values())))

    for dagset in ["driving", "random5", "random6"]:
        src = ROOT / ("config_%s_Random.json" % dagset)
        if not src.exists():
            continue
        cfg = json.loads(src.read_text(encoding="utf-8"))
        cfg["network"]["file"] = "Network/%s.json" % name
        dst = ROOT / ("config_%s_%s.json" % (dagset, name))
        dst.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


if __name__ == "__main__":
    build(100, 20260719, "Random50d4")
    build(150, 20260719, "Random50d6")
