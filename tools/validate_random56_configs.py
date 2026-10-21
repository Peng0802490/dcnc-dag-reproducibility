#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate that config_random5/config_random6 files match DAG node IDs."""
import argparse
import json
from pathlib import Path

def load(p: Path):
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-dir", default="inputs/configs")
    ap.add_argument("--dag-dir", default="inputs/dags")
    ap.add_argument("--workloads", default="random5,random6")
    ap.add_argument("--networks", default="Milan,Random,Roofnet38,FlockLab")
    args = ap.parse_args()

    cfg_dir = Path(args.config_dir)
    dag_dir = Path(args.dag_dir)
    ok = True

    for workload in [x.strip() for x in args.workloads.split(",") if x.strip()]:
        for net in [x.strip() for x in args.networks.split(",") if x.strip()]:
            cfg_p = cfg_dir / f"config_{workload}_{net}.json"
            if not cfg_p.exists():
                print(f"[MISS] {cfg_p}")
                ok = False
                continue

            cfg = load(cfg_p)
            if len(cfg.get("service_dags", [])) != 3:
                print(f"[ERR] {cfg_p}: expected 3 service_dags, got {len(cfg.get('service_dags', []))}")
                ok = False

            for idx, sd in enumerate(cfg.get("service_dags", []), start=1):
                dag_p = dag_dir / f"{workload}_{idx}.json"
                if not dag_p.exists():
                    print(f"[MISS] {dag_p}")
                    ok = False
                    continue

                dag = load(dag_p)
                node_ids = {n["id"] for n in dag["nodes"]}
                src_ids = {n["id"] for n in dag["nodes"] if n.get("type") == "source"}
                sink_ids = {n["id"] for n in dag["nodes"] if n.get("type") == "sink"}
                allowed_ids = set(sd.get("allowed", {}).keys())
                cfg_src = set(sd.get("sources", {}).keys())
                cfg_sink = set(sd.get("sinks", {}).keys())

                if allowed_ids != node_ids:
                    print(f"[ERR] {cfg_p}: service_dag {idx} allowed keys != DAG node IDs")
                    print("  missing in allowed:", sorted(node_ids - allowed_ids))
                    print("  extra in allowed:", sorted(allowed_ids - node_ids))
                    ok = False
                if cfg_src != src_ids:
                    print(f"[ERR] {cfg_p}: service_dag {idx} sources != source nodes")
                    print("  expected:", sorted(src_ids), "got:", sorted(cfg_src))
                    ok = False
                if cfg_sink != sink_ids:
                    print(f"[ERR] {cfg_p}: service_dag {idx} sinks != sink nodes")
                    print("  expected:", sorted(sink_ids), "got:", sorted(cfg_sink))
                    ok = False

            print(f"[OK] {cfg_p}")

    raise SystemExit(0 if ok else 1)

if __name__ == "__main__":
    main()
