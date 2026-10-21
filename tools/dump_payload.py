#!/usr/bin/env python3
"""Write a few representative DynVMP payloads to disk so the Python-2 bridge can
be profiled without running the whole simulator."""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/dcnc_dag_py3/src"))

from dcnc_sim.mapping import DynVMPBridgeSolver
from dcnc_sim.models import Commodity, DistributedComputingNetwork, ServiceDAG
from dcnc_sim.workloads import restrict_to_allowed_compute_nodes

ROOT = Path(os.path.expanduser("~/dcnc_dag_py3"))


def load_explicit_config(config_path):
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


config = sys.argv[1]
out = sys.argv[2]
n = int(sys.argv[3]) if len(sys.argv) > 3 else 30

net, comms = load_explicit_config(ROOT / config)
solver = DynVMPBridgeSolver(net, bridge_cmd=["true"], seed=1)
rng = random.Random(20260719)

with open(out, "w") as f:
    for i in range(n):
        scale = [0.5, 5.0, 50.0, 500.0][i % 4]
        q_link = {(str(u), str(v)): (0.0 if rng.random() < 0.25 else rng.expovariate(1.0 / scale))
                  for (u, v) in net.edges_all()}
        q_node = {str(u): (0.0 if rng.random() < 0.25 else rng.expovariate(1.0 / scale))
                  for u in net.nodes_all()}
        c = comms[i % len(comms)]
        f.write(json.dumps(solver._payload(c.service_dag, c, q_link, q_node)) + "\n")
print("wrote %d payloads to %s" % (n, out))
