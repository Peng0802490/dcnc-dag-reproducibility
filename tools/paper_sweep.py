#!/usr/bin/env python3
"""Uniform sweep driver for the topology-level delay curves (Figs. 3-5).

One process per (case, policy, T_f, seed, rate) point, run in-process rather
than as a subprocess so that thousands of points fit in minutes on 128 cores.
Every policy in a figure sees the same network, DAG set, slot count, seeds and
rate grid; the valid-mapping rule is the only thing that differs, which is the
fairness condition the paper states in Section VII-A.

Results are appended as JSON lines and keyed, so a rerun skips finished points.

  python tools/paper_sweep.py --spec jobs.json --out results.jsonl --workers 100
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/dcnc_dag_py3/src"))
sys.path.insert(0, os.path.expanduser("~/dcnc_dag_py3/scripts"))

from dcnc_sim.interference import build_activation_policy
from dcnc_sim.mapping import (
    ExactDPSolver,
    NearestToSourceSolver,
    QueueAwareGreedySolver,
    RandomSolver,
)
from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
from dcnc_sim.wireless import IIDOnOffProcess
from dcnc_sim.workloads import CONFIG_ROOT, load_config

# Ingress-adjacent arcs made dynamic on the two sparse topologies, exactly as in
# scripts/run_edge_experiments.py.  The dense measured topologies (RoofNet,
# FlockLab) instead flag every arc in the network file.
PAPER_DYNAMIC_EDGES = {
    "milan": [("1", "3"), ("3", "1"), ("6", "7"), ("7", "6"),
              ("10", "12"), ("12", "10"), ("28", "23"), ("23", "28")],
    "random": [("31", "7"), ("7", "31"), ("35", "3"), ("3", "35"),
               ("40", "7"), ("7", "40"), ("18", "30"), ("30", "18"),
               ("20", "28"), ("28", "20"), ("5", "46"), ("46", "5")],
}

SOLVERS = {
    "exact_dp": ExactDPSolver,
    "greedy": QueueAwareGreedySolver,
    "cts": NearestToSourceSolver,
    "random": RandomSolver,
}

_CACHE: dict = {}


def job_key(j: dict) -> str:
    return "|".join(str(j[k]) for k in
                    ("case", "config", "policy", "solver", "fixed_k", "slots", "seed", "rate"))


def _load(config: str, p_on: float):
    if config in _CACHE:
        return _CACHE[config]
    net, comms = load_config(config)
    with (CONFIG_ROOT / config).open(encoding="utf-8") as f:
        cfg = json.load(f)
    net_file = str(cfg["network"]["file"])
    with (CONFIG_ROOT / net_file).open(encoding="utf-8") as f:
        net_json = json.load(f)

    flagged = {(str(e["from"]), str(e["to"])): float(e.get("p_on", p_on))
               for e in net_json.get("edges", []) if bool(e.get("dynamic", False))}
    if flagged:
        dynamic = flagged
    elif "Milan" in net_file:
        dynamic = {e: p_on for e in PAPER_DYNAMIC_EDGES["milan"]}
    elif "Random" in net_file:
        dynamic = {e: p_on for e in PAPER_DYNAMIC_EDGES["random"]}
    else:
        # dense measured topology with no per-edge flags: stress every arc
        dynamic = {(str(e["from"]), str(e["to"])): p_on for e in net_json["edges"]}

    compute = set()
    for c in comms:
        for f_ in c.service_dag.nodes_all():
            compute.update(c.allowed_nodes(net, f_))
    _CACHE[config] = (net, comms, dynamic, sorted(compute))
    return _CACHE[config]


def run_one(job: dict) -> dict:
    t0 = time.time()
    try:
        p_on = float(job.get("p_on", 0.8))
        net, comms, dynamic, compute = _load(job["config"], p_on)
        policy = job["policy"]
        solver_kind = job["solver"]
        # Only DCNC-DAG carries a frame length; the queue-blind baselines
        # recompute their (queue-independent) mapping every slot.
        fixed_k = int(job["fixed_k"]) if policy == "DCNC-DAG" else 1
        seed = int(job["seed"])
        rate = float(job["rate"])

        wireless = IIDOnOffProcess(net, dynamic, seed=1000 + seed)
        per_rate = rate / max(len(comms), 1)
        cfgs = []
        for idx, commodity in enumerate(comms):
            solver = SOLVERS[solver_kind](net, seed=2000 + 100 * idx + seed)
            cfgs.append(CommodityConfig(commodity, per_rate, solver))

        sim = DCNCSimulator(
            network=net,
            commodity_cfgs=cfgs,
            wireless_process=wireless,
            total_slots=int(job["slots"]),
            seed=3000 + seed,
            scheduler="nto",
            activation_policy=build_activation_policy(job.get("interference", "primary")),
            fixed_k=fixed_k,
            run_label="%s_%s_r%.6f_s%d" % (job["case"], policy, rate, seed),
            progress_every=10 ** 9,
        )
        st = sim.run()
        delivered, pending = int(st.delivered_packets), int(st.pending_packets)
        return dict(
            job,
            key=job_key(job),
            status="ok",
            avg_delay_completed=float(st.avg_delay_completed),
            avg_delay_with_penalty=float(st.avg_delay_with_penalty),
            delivered_packets=delivered,
            pending_packets=pending,
            completion_ratio=delivered / (delivered + pending) if delivered + pending else 1.0,
            routing_oracle_calls=int(st.routing_oracle_calls),
            num_compute_nodes=len(compute),
            dynamic_edges=len(dynamic),
            wall_sec=round(time.time() - t0, 2),
        )
    except Exception as exc:  # noqa: BLE001 - a bad point must not kill the sweep
        return dict(job, key=job_key(job), status="error", error=repr(exc),
                    traceback=traceback.format_exc()[-1500:], wall_sec=round(time.time() - t0, 2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=100)
    args = ap.parse_args()

    jobs = json.loads(Path(args.spec).read_text())
    out = Path(args.out)
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    if r.get("status") == "ok":
                        done.add(r["key"])
                except json.JSONDecodeError:
                    pass
    todo = [j for j in jobs if job_key(j) not in done]
    print("total=%d done=%d todo=%d workers=%d" % (len(jobs), len(done), len(todo), args.workers),
          flush=True)

    n_ok = n_err = 0
    t0 = time.time()
    with out.open("a") as fh, ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, j): j for j in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            if r["status"] == "ok":
                n_ok += 1
            else:
                n_err += 1
                print("  ERROR %s: %s" % (r["key"], r.get("error")), flush=True)
            if i % 25 == 0 or i == len(todo):
                el = time.time() - t0
                print("  %d/%d  ok=%d err=%d  %.0fs elapsed, ~%.0fs left"
                      % (i, len(todo), n_ok, n_err, el, el / i * (len(todo) - i)), flush=True)
    print("DONE ok=%d err=%d in %.0fs" % (n_ok, n_err, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
