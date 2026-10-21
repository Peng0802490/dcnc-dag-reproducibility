"""Observe finite-horizon MoE request ages without changing simulator behavior.

Completed requests contribute their measured arrival-to-completion delay.
Unfinished requests contribute horizon minus their recorded arrival slot.
The default grid is a preview; a plotting CSV can supply the full paper grid.
These runs remain separate from the archived paper campaigns.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import gzip
import hashlib
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "open_source_release"
POLICIES = ("DCNC-DAG-H", "Lazarus-style", "FlexMoE-style")
RATES = {
    "mixtral": {
        "DCNC-DAG-H": (1.10, 1.13, 1.16, 1.19),
        "Lazarus-style": (0.30, 0.35, 0.38, 0.40),
        "FlexMoE-style": (0.44, 0.46, 0.48, 0.50),
    },
    "llama": {
        "DCNC-DAG-H": (0.98, 1.00, 1.02, 1.05),
        "Lazarus-style": (0.25, 0.28, 0.30, 0.32),
        "FlexMoE-style": (0.36, 0.38, 0.40, 0.45),
    },
}
SOURCE_FILES = (
    "scripts/run_skewed_moe_case.py",
    "scripts/run_skewed_moe_milan.py",
    "src/dcnc_sim/simulator.py",
    "src/dcnc_sim/physical.py",
    "src/dcnc_sim/mapping.py",
    "src/dcnc_sim/models.py",
    "src/dcnc_sim/interference.py",
    "src/dcnc_sim/wireless.py",
    "legacy_inputs/Network/Milan.json",
)


def source_hashes() -> dict[str, str]:
    return {p: hashlib.sha256((RELEASE / p).read_bytes()).hexdigest()
            for p in SOURCE_FILES}


def import_simulator():
    for p in (RELEASE / "src", RELEASE / "scripts"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import run_skewed_moe_case as moe
    import run_skewed_moe_milan as milan
    from dcnc_sim.interference import build_activation_policy
    from dcnc_sim.simulator import CommodityConfig, DCNCSimulator
    from dcnc_sim.wireless import IIDOnOffProcess
    return moe, milan, build_activation_policy, CommodityConfig, DCNCSimulator, IIDOnOffProcess


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def task_key(task: dict) -> str:
    token = format(task["arrival_rate"], ".6g").replace(".", "p")
    return f"{task['model']}_{task['policy']}_r{token}_s{task['seed']}_T{task['horizon']}"


def load_rates(path: Path) -> dict:
    path = path.resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("The reference plotting CSV must stay inside the repository")
    rates = {model: {policy: [] for policy in POLICIES} for model in RATES}
    aliases = {"Lazarus": "Lazarus-style", "FlexMoE": "FlexMoE-style"}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            model = row.get("model", row.get("workload", "")).lower().split("-")[0]
            policy = aliases.get(row["policy"], row["policy"])
            rate = float(row["arrival_rate"])
            if model not in rates or policy not in POLICIES or rate <= 0:
                raise ValueError(f"Invalid plotting point: {row}")
            if rate in rates[model][policy]:
                raise ValueError(f"Duplicate plotting point: {model}/{policy}/{rate}")
            rates[model][policy].append(rate)
    for model in rates:
        for policy in POLICIES:
            if not rates[model][policy]:
                raise ValueError(f"No plotting points for {model}/{policy}")
            rates[model][policy].sort()
    return rates


def memoize_paths_within_mapping_call(solver) -> dict:
    """Reuse identical pure Dijkstra results only within one compute call.

    The original oracle supplies every cache miss, including its tie-breaking.
    Cache keys keep the exact edge-cost callable alive; each mapping call
    clears the cache so queue prices are never reused across time slots.
    """
    original_path = solver.oracle.shortest_path
    original_compute = solver.compute
    cache = {}
    counters = {"path_queries": 0, "path_cache_hits": 0}

    def path(src, dst, edge_cost):
        counters["path_queries"] += 1
        key = (str(src), str(dst), edge_cost)
        if key not in cache:
            cache[key] = original_path(src, dst, edge_cost)
        else:
            counters["path_cache_hits"] += 1
        distance, edges = cache[key]
        return distance, list(edges)

    def compute(*args, **kwargs):
        cache.clear()
        try:
            return original_compute(*args, **kwargs)
        finally:
            cache.clear()

    solver.oracle.shortest_path = path
    solver.compute = compute
    return counters


class ProgressHandler(logging.Handler):
    def __init__(self, path: Path, task: dict):
        super().__init__(logging.INFO)
        self.path, self.task = path, task

    def emit(self, record):
        if record.msg.startswith("Progress |"):
            values = record.args
            write_json(self.path, {
                "state": "running", "model": self.task["model"],
                "policy": self.task["policy"], "rate": self.task["arrival_rate"],
                "slot": int(values[1]), "horizon": int(values[2]),
                "completed": int(values[5]), "pending": int(values[6]),
                "updated_unix": time.time(),
            })


def run_one(task: dict) -> dict:
    moe, milan, activation, CommodityConfig, DCNCSimulator, wireless_type = import_simulator()
    key = task_key(task)
    out = Path(task["output"])
    row_path = out / "runs" / f"{key}.json"
    if row_path.exists():
        row = json.loads(row_path.read_text(encoding="utf-8"))
        if row["protocol_id"] != task["protocol_id"]:
            raise RuntimeError(f"Cached protocol differs: {row_path}")
        return row

    if task.get("reuse_from"):
        reference = Path(task["reuse_from"])
        reference_row = reference / "runs" / f"{key}.json"
        if reference_row.exists():
            row = json.loads(reference_row.read_text(encoding="utf-8"))
            assert row["protocol_id"] == task["reuse_protocol_id"]
            assert all(row[field] == task[field] for field in
                       ("model", "policy", "arrival_rate", "seed", "horizon", "memoize_routing"))
            pending_file = (reference / row["pending_arrivals_file"].replace("\\", "/")).resolve()
            assert pending_file.is_relative_to(reference)
            assert hashlib.sha256(pending_file.read_bytes()).hexdigest() == row["pending_arrivals_sha256"]
            destination = out / "pending_arrivals" / pending_file.name
            shutil.copyfile(pending_file, destination)
            row.update(protocol_id=task["protocol_id"],
                       pending_arrivals_file=str(destination.relative_to(out)),
                       reused_from=str(reference_row.relative_to(ROOT)),
                       original_protocol_id=row.get("original_protocol_id", task["reuse_protocol_id"]))
            write_json(row_path, row)
            write_json(out / "progress" / f"{key}.json", {"state": "completed", "slot": task["horizon"], **row})
            return row

    logger = logging.getLogger("censored_preview." + key)
    logger.handlers.clear()
    logger.addHandler(ProgressHandler(out / "progress" / f"{key}.json", task))
    logger.setLevel(logging.INFO)
    logger.propagate = False
    model, policy, rate, seed = (task[k] for k in ("model", "policy", "arrival_rate", "seed"))
    horizon = task["horizon"]
    workload = model + "_skewed_pr_multitenant"
    network, commodities, _ = milan.make_milan_workload(workload, 0.60)
    wireless = wireless_type(network, {e: milan.P_ON for e in milan.DYNAMIC_EDGES}, seed=1000 + seed)
    if policy == "Lazarus-style":
        solver = milan.PhysicalBacklogLeastLoadedSolver(network, seed=200000 + seed, logger=logger, tentative=True)
    elif policy == "FlexMoE-style":
        solver = milan.QueueRoutedRoundRobinSolver(network, seed=300000 + seed, logger=logger)
    else:
        solver = moe.build_solver(policy, network, seed, logger, "greedy", None)
    path_counts = memoize_paths_within_mapping_call(solver) if task.get("memoize_routing") else {}
    cfgs = [CommodityConfig(commodities[0], rate * 0.60, solver),
            CommodityConfig(commodities[1], rate * 0.40, solver)]
    sim = DCNCSimulator(
        network=network, commodity_cfgs=cfgs, wireless_process=wireless,
        total_slots=horizon, seed=700000 + seed, scheduler="nto",
        activation_policy=activation("primary"), fixed_k=1, logger=logger,
        run_label=key, progress_every=10000,
    )
    if isinstance(solver, milan.PhysicalBacklogLeastLoadedSolver):
        solver.physical = sim.physical_network

    started = time.perf_counter()
    stats = sim.run()
    wall_seconds = time.perf_counter() - started
    physical = sim.physical_network
    pending_births = physical.job_born_time
    arrivals, completed, pending = (int(getattr(stats, name)) for name in
        ("total_service_units", "completed_service_units", "pending_service_units"))
    assert arrivals == completed + pending
    assert len(pending_births) == pending, "All fixed-K requests must be represented in job_born_time"
    assert sim.routing_mode == "fixed_k"
    assert all(0 <= born < horizon for born in pending_births.values())
    pending_age_sum = sum(horizon - int(born) for born in pending_births.values())
    completed_sum = float(physical.service_delay_sum_completed)
    lower_bound_mean = (completed_sum + pending_age_sum) / arrivals if arrivals else 0.0
    assert 0 <= lower_bound_mean <= horizon

    # Save every unfinished request's real recorded arrival slot for audit.
    pending_file = out / "pending_arrivals" / f"{key}.csv.gz"
    with gzip.open(pending_file, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("request_id", "arrival_slot", "cutoff_T", "delay_lower_bound_slots"))
        for job, born in sorted(pending_births.items(), key=lambda item: (item[1], item[0])):
            writer.writerow((job, born, horizon, horizon - born))
    row = {
        "protocol_id": task["protocol_id"], "model": model, "policy": policy,
        "arrival_rate": rate, "seed": seed, "horizon": horizon,
        "total_arrivals": arrivals, "total_completions": completed,
        "unfinished_requests": pending, "completion_ratio": completed / arrivals if arrivals else 1.0,
        "completed_delay_sum_slots": completed_sum,
        "mean_completion_delay": float(stats.avg_service_delay_completed),
        "unfinished_age_sum_slots": pending_age_sum,
        "mean_unfinished_age_slots": pending_age_sum / pending if pending else 0.0,
        "mean_service_delay_lower_bound": lower_bound_mean,
        "completed_contribution": completed_sum / arrivals if arrivals else 0.0,
        "unfinished_contribution": pending_age_sum / arrivals if arrivals else 0.0,
        "fixed_100000_penalty_comparison": (completed_sum + 100000 * pending) / arrivals if arrivals else 0.0,
        "routing_oracle_calls": int(stats.routing_oracle_calls),
        "wall_seconds": wall_seconds,
        "pending_arrivals_file": str(pending_file.relative_to(out)),
        "pending_arrivals_sha256": hashlib.sha256(pending_file.read_bytes()).hexdigest(),
        "memoize_routing": bool(task.get("memoize_routing", False)),
        "path_queries": path_counts.get("path_queries", 0),
        "path_cache_hits": path_counts.get("path_cache_hits", 0),
        "reused_from": "",
        "original_protocol_id": task["protocol_id"],
    }
    write_json(row_path, row)
    write_json(out / "progress" / f"{key}.json", {"state": "completed", "slot": horizon, **row})
    return row


def save_rows(out: Path, rows: list[dict]) -> None:
    if not rows:
        return
    rows = sorted(rows, key=lambda r: (r["model"], r["policy"], r["arrival_rate"], r["seed"]))
    with (out / "run_results.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot(out: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".runtime" / "matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    frame = pd.read_csv(out / "run_results.csv")
    expected = json.loads((out / "protocol.json").read_text())["expected_jobs"]
    if len(frame) != expected:
        raise RuntimeError(f"Incomplete preview: {len(frame)}/{expected}")
    grouped = frame.groupby(["model", "policy", "arrival_rate"], as_index=False).agg(
        mean_lower_bound=("mean_service_delay_lower_bound", "mean"),
        mean_completed_only=("mean_completion_delay", "mean"),
        mean_penalized=("fixed_100000_penalty_comparison", "mean"),
        completion_ratio=("completion_ratio", "mean"),
        mean_unfinished_age=("mean_unfinished_age_slots", "mean"),
        seeds=("seed", "nunique"),
    )
    grouped.to_csv(out / "plot_data.csv", index=False)
    plt.rcParams.update({"font.family": "Times New Roman", "font.size": 13,
                        "axes.labelsize": 15, "axes.titlesize": 16,
                        "pdf.fonttype": 42, "ps.fonttype": 42})
    colors = {"DCNC-DAG-H": "#1f77b4", "Lazarus-style": "#d62728", "FlexMoE-style": "#2ca02c"}
    markers = {"DCNC-DAG-H": "D", "Lazarus-style": "s", "FlexMoE-style": "^"}
    labels = {"DCNC-DAG-H": "DCNC-DAG-H", "Lazarus-style": "Lazarus-inspired", "FlexMoE-style": "FlexMoE-inspired"}
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.6), sharey=True)
    for ax, model, panel in zip(axes, ("mixtral", "llama"), ("a", "b")):
        for policy in POLICIES:
            group = grouped[(grouped.model == model) & (grouped.policy == policy)].sort_values("arrival_rate")
            ax.plot(group.arrival_rate, group.mean_lower_bound, color=colors[policy],
                    marker=markers[policy], linewidth=2, markersize=6, label=labels[policy])
        ax.set_title(f"({panel}) {model.capitalize()}")
        ax.set_xlabel("Arrival rate (requests/slot)")
        ax.grid(alpha=0.22)
        ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 4))
    # Set shared limits after both models have been drawn; setting the first
    # axis early would disable autoscaling and clip larger second-panel values.
    axes[0].set_ylim(0, float(grouped.mean_lower_bound.max()) * 1.08)
    axes[0].set_ylabel("Mean service-delay lower bound (slots)")
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles, names, loc="upper center", ncol=3, frameon=True, bbox_to_anchor=(0.5, 1.0))
    horizon = int(frame.horizon.iloc[0])
    seeds = ",".join(str(int(s)) for s in sorted(frame.seed.unique()))
    fig.text(0.5, 0.015, f"Continuous arrivals for T={horizon:,} slots; seed(s) {seeds}. Unfinished delay = T - arrival slot.", ha="center", fontsize=11)
    fig.tight_layout(rect=(0, 0.045, 1, 0.90))
    for ext in ("png", "pdf"):
        fig.savefig(out / f"MoE_censored_delay_two_panel.{ext}", dpi=200)
    plt.close(fig)

    fig, axes = plt.subplots(2, 3, figsize=(13.4, 7.4))
    for i, model in enumerate(("mixtral", "llama")):
        for j, policy in enumerate(POLICIES):
            ax = axes[i, j]
            group = grouped[(grouped.model == model) & (grouped.policy == policy)].sort_values("arrival_rate")
            ax.plot(group.arrival_rate, group.mean_completed_only, "o--", color="#777777", label="Completed-only")
            ax.plot(group.arrival_rate, group.mean_lower_bound, "o-", color=colors[policy], label="All-request lower bound")
            ax.set_title(model.capitalize() + " / " + labels[policy], fontsize=13)
            ax.set_xlabel("Arrival rate")
            ax.set_ylabel("Delay (slots)")
            ax.set_ylim(bottom=0)
            ax.grid(alpha=0.22)
            ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 4))
    handles, names = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, names, loc="upper center", ncol=2)
    fig.text(0.5, 0.015, f"Same runs: T={horizon:,} slots; seed(s) {seeds}. Unfinished delay = T - arrival slot.", ha="center", fontsize=11)
    fig.tight_layout(rect=(0, 0.045, 1, 0.95))
    for ext in ("png", "pdf"):
        fig.savefig(out / f"MoE_censored_vs_completed.{ext}", dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--horizon", type=int, default=100000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0])
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--memoize-routing", action="store_true")
    parser.add_argument("--plot-only", action="store_true")
    parser.add_argument("--rates-csv", type=Path)
    parser.add_argument("--reuse-from", type=Path)
    parser.add_argument("--allow-compatible-runtime-reuse", action="store_true")
    parser.add_argument("--longest-first", action="store_true")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT):
        raise ValueError("Outputs must stay inside the paper repository")
    if args.plot_only:
        plot(out)
        return
    rates = load_rates(args.rates_csv) if args.rates_csv else RATES
    out.mkdir(parents=True, exist_ok=True)
    for directory in ("runs", "progress", "pending_arrivals"):
        (out / directory).mkdir(exist_ok=True)
    config = {"horizon": args.horizon, "seeds": args.seeds, "rates": rates,
              "source_sha256": source_hashes(), "metric": "(completed_delay_sum + sum(T-arrival_slot for pending))/total_arrivals",
              "cutoff_convention": "T is the boundary after slots 0..T-1; completed delays retain the original simulator convention",
              "python_version": sys.version, "python_hash_seed": os.environ.get("PYTHONHASHSEED", "unset"),
              "policy_source": "maintained open_source_release/scripts/run_skewed_moe_milan.py",
              "routing": "queue-aware routes for all three policies; unchanged maintained runner", "smoke": args.smoke,
              "memoize_routing": args.memoize_routing}
    if args.rates_csv:
        config["reference_plot_csv"] = str(args.rates_csv.resolve().relative_to(ROOT))
        config["reference_plot_csv_sha256"] = hashlib.sha256(args.rates_csv.read_bytes()).hexdigest()
    if args.allow_compatible_runtime_reuse:
        compatibility_path = out.parent / "runtime_compatibility_server64.json"
        compatibility = json.loads(compatibility_path.read_text(encoding="utf-8"))
        versions = {name: importlib.metadata.version(name) for name in
                    ("numpy", "pandas", "matplotlib", "scipy")}
        assert compatibility["status"] == "PASS"
        assert compatibility["server_python"] == sys.version
        assert compatibility["matching_dependency_versions"] == versions
        assert len(compatibility["independent_100000_slot_replays"]) >= 3
        assert compatibility["source_hashes_exactly_match"]
        assert compatibility["unfinished_arrival_records_exactly_match"]
        config["compatible_runtime_reuse"] = {
            "python_release": sys.version.split()[0],
            "dependency_versions": versions,
            "compatibility_record": str(compatibility_path.relative_to(ROOT)),
            "compatibility_record_sha256": hashlib.sha256(compatibility_path.read_bytes()).hexdigest(),
            "condition": "Matching dependency versions and exact independent full-horizon replays verified before migration",
        }
    reuse_from = args.reuse_from.resolve() if args.reuse_from else None
    reuse_protocol = None
    if reuse_from:
        if not reuse_from.is_relative_to(ROOT):
            raise ValueError("Reused results must stay inside the repository")
        reuse_protocol = json.loads((reuse_from / "protocol.json").read_text(encoding="utf-8"))
        for field in ("horizon", "source_sha256", "metric", "cutoff_convention",
                      "python_version", "python_hash_seed", "policy_source", "routing", "smoke", "memoize_routing"):
            if field == "python_version" and args.allow_compatible_runtime_reuse:
                if reuse_protocol[field].split()[0] != config[field].split()[0]:
                    raise RuntimeError("Cannot reuse results with a different Python release")
                continue
            if reuse_protocol[field] != config[field]:
                raise RuntimeError(f"Cannot reuse results with different {field}")
    protocol_id = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    tasks = [{"model": model, "policy": policy, "arrival_rate": rate, "seed": seed,
              "horizon": args.horizon, "output": str(out), "protocol_id": protocol_id,
              "memoize_routing": args.memoize_routing,
              "reuse_from": str(reuse_from) if reuse_from else None,
              "reuse_protocol_id": reuse_protocol["protocol_id"] if reuse_protocol else None}
             for model in ("mixtral", "llama") for policy in POLICIES
             for rate in (rates[model][policy][:1] if args.smoke else rates[model][policy])
             for seed in args.seeds]
    # Start one task per policy/model before running the remaining rate points.
    tasks.sort(key=lambda t: (rates[t["model"]][t["policy"]].index(t["arrival_rate"]),
                              POLICIES.index(t["policy"]), t["model"], t["seed"]))
    if args.longest_first:
        # Congested DCNC endpoints can dominate the final wait if started last.
        tasks.sort(key=lambda t: (t["policy"] == "DCNC-DAG-H", t["arrival_rate"]), reverse=True)
    config.update(protocol_id=protocol_id, expected_jobs=len(tasks), workers=args.workers)
    protocol_path = out / "protocol.json"
    if protocol_path.exists():
        previous = json.loads(protocol_path.read_text(encoding="utf-8"))
        if previous["protocol_id"] != protocol_id:
            raise RuntimeError("Refusing to mix different protocols in an existing output directory")
    else:
        write_json(protocol_path, config)
    print(f"Starting {len(tasks)} jobs; horizon={args.horizon}; seeds={args.seeds}; workers={args.workers}", flush=True)
    rows = []
    try:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(run_one, task): task for task in tasks}
            for future in as_completed(futures):
                row = future.result()
                rows.append(row)
                save_rows(out, rows)
                print(f"[{len(rows)}/{len(tasks)}] {row['model']} {row['policy']} rate={row['arrival_rate']:.3f} "
                      f"cr={row['completion_ratio']:.4f} completed={row['mean_completion_delay']:.2f} "
                      f"lower_bound={row['mean_service_delay_lower_bound']:.2f} seconds={row['wall_seconds']:.1f}", flush=True)
    finally:
        save_rows(out, rows)
    assert source_hashes() == config["source_sha256"], "Original simulator sources changed during the preview"
    if not args.no_plot:
        plot(out)
    write_json(out / "completion.json", {"completed_jobs": len(rows), "expected_jobs": len(tasks),
               "original_source_hashes_unchanged": True, "protocol_id": protocol_id})
    print(out / ("run_results.csv" if args.no_plot else "MoE_censored_delay_two_panel.png"), flush=True)


if __name__ == "__main__":
    main()
