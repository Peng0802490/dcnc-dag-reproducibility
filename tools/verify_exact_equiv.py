#!/usr/bin/env python3
"""Check that ExactEnumerationSolver returns the same optimum as the DynVMP bridge.

Both are supposed to compute the minimum-total-cost valid mapping for a DAG onto
the physical network under the current virtual-queue state.  If they agree, the
in-process enumeration can replace the 24 s/slot Python-2 subprocess and the
DCNC-DAG rate sweeps become affordable.

Random queue states are drawn at several magnitudes so that both the early-slot
regime (all queues near zero, many ties) and the congested regime are covered.
"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/dcnc_dag_py3/src"))

from dcnc_sim.mapping import DynVMPBridgeSolver, ExactDPSolver
from dcnc_sim.models import Commodity, DistributedComputingNetwork, ServiceDAG
from dcnc_sim.workloads import restrict_to_allowed_compute_nodes

ROOT = Path(os.path.expanduser("~/dcnc_dag_py3"))


def load_explicit_config(config_path):
    """Same loader as scripts/run_project_case.py, inlined because that module
    imports a solver name that no longer exists."""
    config_path = Path(config_path).resolve()
    base = config_path.parent
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    net = DistributedComputingNetwork.from_json(base / cfg["network"]["file"])
    commodities = []
    for idx, scfg in enumerate(cfg["service_dags"]):
        dag = ServiceDAG.from_json(base / scfg["file"])
        commodities.append(
            Commodity(
                name=scfg.get("name", "commodity_%d" % idx),
                service_dag=dag,
                src_nodes={str(k): str(v) for k, v in scfg.get("sources", {}).items()},
                dst_nodes={str(k): str(v) for k, v in scfg.get("sinks", {}).items()},
                allowed={str(k): [str(u) for u in v] for k, v in (scfg.get("allowed") or {}).items()},
            )
        )
    restrict_to_allowed_compute_nodes(net, commodities)
    return net, commodities
BRIDGE = ["bash", str(ROOT / "tools/run_dynvmp_bridge.sh")]
N_STATES = int(sys.argv[2]) if len(sys.argv) > 2 else 10
CONFIG = sys.argv[1] if len(sys.argv) > 1 else "inputs/configs/config_driving_Milan.json"


def sample_state(net, rng, scale):
    q_link = {}
    for (u, v) in net.edges_all():
        q_link[(str(u), str(v))] = 0.0 if rng.random() < 0.25 else rng.expovariate(1.0 / scale)
    q_node = {}
    for u in net.nodes_all():
        q_node[str(u)] = 0.0 if rng.random() < 0.25 else rng.expovariate(1.0 / scale)
    return q_link, q_node


def main():
    import time

    net, comms = load_explicit_config(ROOT / CONFIG)
    exact = ExactDPSolver(net, seed=1)
    dynvmp = DynVMPBridgeSolver(net, bridge_cmd=BRIDGE, seed=1)
    rng = random.Random(20260719)

    same_assign = same_cost = total = 0
    worst_gap = 0.0
    t_exact = t_dyn = 0.0
    for i in range(N_STATES):
        scale = [0.5, 5.0, 50.0, 500.0][i % 4]
        q_link, q_node = sample_state(net, rng, scale)
        for c in comms:
            total += 1
            t = time.perf_counter()
            ve = exact.compute(c.service_dag, c, q_link, q_node)
            t_exact += time.perf_counter() - t
            t = time.perf_counter()
            vd = dynvmp.compute(c.service_dag, c, q_link, q_node)
            t_dyn += time.perf_counter() - t
            a_ok = ve.assign == vd.assign
            # cost is what the optimizer actually minimises; ties may pick a
            # different but equally good assignment, so cost equality is the
            # real test and assignment equality is the stricter bonus.
            gap = abs(ve.total_cost - vd.total_cost)
            denom = max(1.0, abs(ve.total_cost), abs(vd.total_cost))
            c_ok = gap <= 1e-6 * denom
            same_assign += a_ok
            same_cost += c_ok
            worst_gap = max(worst_gap, gap / denom)
            flag = "" if c_ok else "   <<< COST MISMATCH"
            print("state=%-3d scale=%-6.1f %-12s enum=%.6f dynvmp=%.6f assign_eq=%s%s"
                  % (i, scale, c.name, ve.total_cost, vd.total_cost, a_ok, flag))
            if not c_ok:
                print("    enum  :", ve.assign)
                print("    dynvmp:", vd.assign)
            sys.stdout.flush()

    print("\n%s" % CONFIG)
    print("compared      : %d mappings" % total)
    print("cost equal    : %d/%d" % (same_cost, total))
    print("assign equal  : %d/%d" % (same_assign, total))
    print("worst rel gap : %.3e" % worst_gap)
    print("exact-DP time : %.4f s/call" % (t_exact / total))
    print("DynVMP time   : %.4f s/call  (speedup %.0fx)" % (t_dyn / total, t_dyn / max(t_exact, 1e-12)))
    print("VERDICT       : %s" % ("EQUIVALENT" if same_cost == total else "NOT EQUIVALENT"))


if __name__ == "__main__":
    main()
