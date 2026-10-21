#!/usr/bin/env python3
"""Recompute paper-facing claims from the evidence shipped in this artifact."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

if __package__:
    from .maintain_artifact import license_selection_issues
    from .verify_table6_results import verify_results
    from .verify_paper_update import verify_update
else:
    from maintain_artifact import license_selection_issues
    from verify_table6_results import verify_results
    from verify_paper_update import verify_update


ROOT = Path(__file__).resolve().parents[1]
CLAIMS_PATH = ROOT / "manifests" / "claims.json"
POLICY_JSONL = [
    "pilot.jsonl",
    "main.jsonl",
    "ext.jsonl",
    "phase2.jsonl",
    "followup.jsonl",
    "access.jsonl",
    "common.jsonl",
    "dense.jsonl",
]


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=tol)


def read_jsonl(paths: list[Path]) -> list[dict]:
    """Read successful records and de-duplicate campaign refinements by run key."""
    records: dict[str, dict] = {}
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("status") != "ok":
                    continue
                key = row.get("key") or json.dumps(
                    [
                        row.get("case"), row.get("policy"), row.get("solver"),
                        row.get("fixed_k", 1), row.get("slots"), row.get("seed"),
                        row.get("rate"),
                    ],
                    sort_keys=True,
                )
                records[key] = row
    return list(records.values())


def verify_external_paper(
    manifest: dict, paper_path: Path, failures: list[str]
) -> None:
    """Bind this evidence snapshot to an explicitly supplied paper PDF."""
    if not paper_path.is_file():
        print(
            "[FAIL] metadata/upstream-paper-sha256: "
            "observed='<missing>' expected="
            f"{manifest['paper']['sha256']!r}"
        )
        failures.append("metadata/upstream-paper-sha256")
        return
    observed = hashlib.sha256(paper_path.read_bytes()).hexdigest().upper()
    check_equal(
        "metadata/upstream-paper-sha256",
        observed,
        str(manifest["paper"]["sha256"]).upper(),
        failures,
    )


def threshold(
    records: list[dict], case: str, policy: str, solver: str, fixed_k: int = 1
) -> float:
    groups: dict[float, dict[int, float]] = defaultdict(dict)
    for row in records:
        if (
            row.get("case") == case
            and row.get("policy") == policy
            and row.get("solver") == solver
            and int(row.get("fixed_k", 1)) == int(fixed_k)
        ):
            groups[float(row["rate"])][int(row["seed"])] = float(
                row["completion_ratio"]
            )
    accepted = []
    for rate, seed_values in groups.items():
        if len(seed_values) >= 3 and sum(seed_values.values()) / len(seed_values) >= 0.95:
            accepted.append(rate)
    if not accepted:
        raise AssertionError(
            f"no three-seed 0.95-gate point for {case}/{policy}/{solver}/K={fixed_k}"
        )
    return max(accepted)


def check_equal(name: str, observed, expected, failures: list[str], tol=1e-9) -> None:
    if isinstance(expected, (float, int)) and isinstance(observed, (float, int)):
        ok = close(float(observed), float(expected), tol)
    else:
        ok = observed == expected
    label = "PASS" if ok else "FAIL"
    print(f"[{label}] {name}: observed={observed!r} expected={expected!r}")
    if not ok:
        failures.append(name)


def verify_manifest_metadata(manifest: dict, failures: list[str]) -> None:
    """Keep package metadata and fail-closed release gates synchronized."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE)
    project_version = match.group(1) if match else None
    check_equal(
        "metadata/artifact-version",
        manifest.get("artifact_version"),
        project_version,
        failures,
    )

    paper = manifest.get("paper", {})
    paper_hash = str(paper.get("sha256", "")).upper()
    check_equal(
        "metadata/paper-sha256-format",
        bool(re.fullmatch(r"[0-9A-F]{64}", paper_hash)),
        True,
        failures,
    )
    moe_audit = json.loads(
        (ROOT / manifest["claims"]["moe"]["audit_evidence"]).read_text(
            encoding="utf-8"
        )
    )
    table6_audit = json.loads(
        (ROOT / manifest["claims"]["table6"]["timing_audit"]).read_text(
            encoding="utf-8"
        )
    )
    check_equal(
        "metadata/paper-binding/moe-audit",
        str(moe_audit["paper_pdf_sha256"]).upper(),
        paper_hash,
        failures,
    )
    check_equal(
        "metadata/paper-binding/table6-audit",
        str(table6_audit["paper_source"]["sha256"]).upper(),
        paper_hash,
        failures,
    )
    check_equal(
        "metadata/paper-binding/table6-filename",
        table6_audit["paper_source"]["filename"],
        paper.get("filename"),
        failures,
    )

    open_gates = manifest.get("open_gates", [])
    check_equal(
        "metadata/open-gates-unique",
        len(open_gates),
        len(set(open_gates)),
        failures,
    )
    claims = manifest["claims"]
    expected_gate_state = {
        "top-level-license-not-selected": bool(license_selection_issues(ROOT)),
        "moe-paper-table-disagrees-with-raw-results": (
            claims["moe"]["status"] != "exact"
        ),
        "table6-100k-dynvmp-campaign-pending": (
            claims["table6"].get("campaign_status") != "complete"
        ),
        "table6-paper-timing-disagrees-with-raw-results": (
            claims["table6"].get("campaign_status") == "complete"
            and claims["table6"].get("timing_status") != "exact-source-provenance"
        ),
    }
    for gate, should_be_open in expected_gate_state.items():
        check_equal(
            f"metadata/gate/{gate}",
            gate in open_gates,
            should_be_open,
            failures,
        )
    check_equal(
        "metadata/release-ready",
        bool(manifest.get("release_ready")),
        not bool(open_gates),
        failures,
    )


def verify_main_thresholds(claims: dict, failures: list[str]) -> None:
    base = ROOT / "evidence" / "main_sweeps"
    records = read_jsonl([base / name for name in POLICY_JSONL])

    driving_specs = {
        ("Milan", "DCNC-DAG"): ("driving_milan", "DCNC-DAG", "exact_dp"),
        ("Milan", "DCNC-DAG-H"): ("driving_milan", "DCNC-DAG", "greedy"),
        ("Milan", "CTS"): ("driving_milan", "CTS", "cts"),
        ("Milan", "Randomized"): ("driving_milan", "Random", "random"),
        ("Random", "DCNC-DAG"): ("drv_rand_q45", "DCNC-DAG", "exact_dp"),
        ("Random", "DCNC-DAG-H"): ("drv_rand_q45", "DCNC-DAG", "greedy"),
        ("Random", "CTS"): ("drv_rand_q45", "CTS", "cts"),
        ("Random", "Randomized"): ("drv_rand_q45", "Random", "random"),
    }
    for (topology, label), spec in driving_specs.items():
        observed = threshold(records, *spec)
        expected = claims["driving"]["thresholds"][topology][label]
        check_equal(f"driving/{topology}/{label}", observed, expected, failures)

    exact_specs = {
        "Milan": ("r6_milan", "DCNC-DAG", "exact_dp"),
        "Random": ("r6_random", "DCNC-DAG", "exact_dp"),
        "RoofNet": ("rn_access", "DCNC-DAG", "exact_dp"),
        "FlockLab": ("fl_access", "DCNC-DAG", "exact_dp"),
    }
    conventional_specs = {
        "Milan": [("r6_milan", "CTS", "cts"), ("r6_milan", "Random", "random")],
        "Random": [("r6_random", "CTS", "cts"), ("r6_random", "Random", "random")],
        "RoofNet": [("rn_access", "CTS", "cts"), ("rn_access", "Random", "random")],
        "FlockLab": [("fl_access", "CTS", "cts"), ("fl_access", "Random", "random")],
    }
    for topology, spec in exact_specs.items():
        observed = threshold(records, *spec)
        expected = claims["random_dag"]["exact_thresholds"][topology]
        check_equal(f"random-dag/{topology}/exact", observed, expected, failures)
        baseline = max(threshold(records, *candidate) for candidate in conventional_specs[topology])
        expected_base = claims["random_dag"]["best_baseline_thresholds"][topology]
        check_equal(
            f"random-dag/{topology}/best-conventional-baseline",
            baseline,
            expected_base,
            failures,
        )


def verify_frame_length(claims: dict, failures: list[str]) -> None:
    path = ROOT / claims["frame_length"]["evidence"]
    records = read_jsonl([path])
    check_equal("frame-length/record-count", len(records), claims["frame_length"]["records"], failures)
    check_equal("frame-length/seeds", sorted({int(r["seed"]) for r in records}), claims["frame_length"]["seeds"], failures)
    check_equal("frame-length/slots", sorted({int(r["slots"]) for r in records}), [claims["frame_length"]["slots"]], failures)
    for topology, case in (("Milan", "k100k_milan"), ("Random", "k100k_random")):
        for k_text, expected in claims["frame_length"]["thresholds"][topology].items():
            observed = threshold(records, case, "DCNC-DAG", "exact_dp", int(k_text))
            check_equal(f"frame-length/{topology}/K={k_text}", observed, expected, failures)


def verify_workflow(claims: dict, failures: list[str]) -> None:
    path = ROOT / claims["workflow"]["evidence"]
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    observed = {(r["workflow"], r["policy"]): float(r["lambda_hat"]) for r in rows}
    for workflow, policies in claims["workflow"]["thresholds"].items():
        for policy, expected in policies.items():
            check_equal(
                f"workflow/{workflow}/{policy}",
                observed[(workflow, policy)],
                expected,
                failures,
            )


def verify_lp(claims: dict, failures: list[str]) -> None:
    path = ROOT / claims["lp_capacity"]["evidence"] / "results" / "canonical" / "metadata.json"
    observed = json.loads(path.read_text(encoding="utf-8"))["lp_lambda_star"]
    check_equal("lp-capacity/lambda-star", observed, claims["lp_capacity"]["lambda_star"], failures)


def verify_fifo(claims: dict, failures: list[str]) -> None:
    path = ROOT / claims["fifo_nto"]["evidence"]
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    selected = {
        row["policy"]: row
        for row in rows
        if row["experiment"] == "B"
        and close(float(row["lambda"]), 0.8)
        and int(row["horizon"]) == claims["fifo_nto"]["lambda_0_8_horizon"]
    }
    check_equal(
        "fifo/lambda=0.8/final-backlog",
        float(selected["FIFO"]["mean_final_backlog"]),
        claims["fifo_nto"]["fifo_mean_final_backlog"],
        failures,
    )
    check_equal(
        "nto/lambda=0.8/final-backlog",
        float(selected["NTO"]["mean_final_backlog"]),
        claims["fifo_nto"]["nto_mean_final_backlog"],
        failures,
    )


def verify_moe(claims: dict, failures: list[str]) -> None:
    current = claims["moe"]
    audit = json.loads((ROOT / current["audit_evidence"]).read_text(encoding="utf-8"))
    check_equal("moe/current-paper", audit["paper_claims"], current["paper"], failures)
    historical = audit["historical_claim"]
    check_equal("moe/unchanged-raw-results", current["observed"], historical["observed"], failures)
    for field in ("raw_evidence", "evidence", "seeds", "horizon", "completion_gate", "grid_points_per_policy", "rows_per_model"):
        check_equal(f"moe/current-protocol/{field}", current[field], historical[field], failures)
    verify_historical_moe({"moe": historical}, failures)
    for model, values in current["observed"].items():
        for policy, observed in values.items():
            check_equal(f"moe/current-paper/{model}/{policy}", round(observed, 2), current["paper"][model][policy], failures)
    check_equal("moe/current-status", current["status"], "exact", failures)
    if __package__:
        from .verify_moe_censored import verify_results as verify_figures
    else:
        from verify_moe_censored import verify_results as verify_figures
    try:
        report = verify_figures(ROOT)
    except (ValueError, OSError, KeyError) as error:
        failures.append(f"moe/figure-data: {error}")
    else:
        print(f"[PASS] moe/latest-figure-data: {report}")
        for field in ("runs", "aggregate_points", "displayed_points"):
            check_equal(f"moe/figure-claim/{field}", report[field], claims["moe_figure"][field], failures)


def verify_historical_moe(claims: dict, failures: list[str]) -> None:
    path = ROOT / claims["moe"]["evidence"]
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    values = {}
    gains = {}
    for row in rows:
        if row["policy"] == "RATIO_vs_better_baseline":
            gains[row["model"]] = float(row["lambda_hat"])
        else:
            values[(row["model"], row["policy"])] = float(row["lambda_hat"])
    for model, expected_values in claims["moe"]["observed"].items():
        for policy, expected in expected_values.items():
            observed = gains[model] if policy == "gain" else values[(model, policy)]
            check_equal(f"moe-summary/{model}/{policy}", observed, expected, failures)

    audit = json.loads(
        (ROOT / claims["moe"]["audit_evidence"]).read_text(encoding="utf-8")
    )
    check_equal(
        "moe-audit/paper-claims",
        audit["paper_claims"],
        claims["moe"]["paper"],
        failures,
    )
    check_equal(
        "moe-audit/paper-protocol-gate",
        audit["threshold_convention_checks"]["paper_protocol_gate"],
        claims["moe"]["completion_gate"],
        failures,
    )
    lineage = audit["manuscript_source_lineage"]
    check_equal(
        "moe-audit/source-lineage/commit-format",
        bool(re.fullmatch(r"[0-9a-f]{40}", lineage["parent_git_commit"])),
        True,
        failures,
    )
    check_equal(
        "moe-audit/source-lineage/blob-format",
        bool(re.fullmatch(r"[0-9a-f]{40}", lineage["source_git_blob"])),
        True,
        failures,
    )
    check_equal(
        "moe-audit/source-lineage/sha256-format",
        bool(re.fullmatch(r"[0-9a-f]{64}", lineage["source_sha256"])),
        True,
        failures,
    )
    check_equal(
        "moe-audit/source-lineage/table-matches-paper",
        lineage["table_rows_match_paper_claims"],
        True,
        failures,
    )
    check_equal(
        "moe-audit/source-lineage/data-files-changed",
        lineage["raw_or_summary_data_files_changed_in_commit"],
        False,
        failures,
    )
    for relative, expected_hash in audit["canonical_file_hashes"].items():
        observed_hash = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        check_equal(f"moe-audit/hash/{relative}", observed_hash, expected_hash, failures)

    remote_revalidation = audit["remote_server_revalidation"]
    remote_thresholds = remote_revalidation["threshold_files"]
    check_equal(
        "moe-audit/remote-threshold-count",
        remote_revalidation["moe_threshold_file_count"],
        len(remote_thresholds),
        failures,
    )
    check_equal(
        "moe-audit/remote-threshold-paths",
        [entry["path"] for entry in remote_thresholds],
        [
            "results_moe_milan/moe_milan/summary/thresholds.csv",
            "results_moe_milan/moe_milan_v2/summary/thresholds.csv",
        ],
        failures,
    )
    check_equal(
        "moe-audit/remote-threshold-hashes",
        [entry["sha256"] for entry in remote_thresholds],
        [
            audit["located_campaigns"]["legacy_milan"]["thresholds_sha256"],
            audit["located_campaigns"]["canonical_milan_v2"]["thresholds_sha256"],
        ],
        failures,
    )
    check_equal(
        "moe-audit/remote-paper-values-supported",
        remote_revalidation["paper_flexmoe_values_supported"],
        False,
        failures,
    )

    raw_root = ROOT / claims["moe"]["raw_evidence"]
    expected_policies = sorted(
        policy for policy in next(iter(claims["moe"]["observed"].values())) if policy != "gain"
    )
    gate = float(claims["moe"]["completion_gate"])
    for model, expected_values in claims["moe"]["observed"].items():
        raw_path = raw_root / f"{model}_runs.csv"
        with raw_path.open(newline="", encoding="utf-8") as handle:
            raw_rows = list(csv.DictReader(handle))
        check_equal(
            f"moe-raw/{model}/row-count",
            len(raw_rows),
            claims["moe"]["rows_per_model"],
            failures,
        )
        check_equal(
            f"moe-raw/{model}/seeds",
            sorted({int(row["seed"]) for row in raw_rows}),
            claims["moe"]["seeds"],
            failures,
        )
        check_equal(
            f"moe-raw/{model}/horizon",
            sorted({int(row["horizon"]) for row in raw_rows}),
            [claims["moe"]["horizon"]],
            failures,
        )
        check_equal(
            f"moe-raw/{model}/policies",
            sorted({row["policy"] for row in raw_rows}),
            expected_policies,
            failures,
        )

        groups: dict[tuple[str, float], dict[int, float]] = defaultdict(dict)
        throughput_groups: dict[
            tuple[str, float], dict[int, float]
        ] = defaultdict(dict)
        for row in raw_rows:
            key = (row["policy"], float(row["arrival_rate"]))
            groups[key][int(row["seed"])] = float(row["completion_ratio"])
            throughput_groups[key][int(row["seed"])] = float(
                row["completed_throughput"]
            )
        check_equal(
            f"moe-raw/{model}/unique-run-keys",
            sum(len(seed_values) for seed_values in groups.values()),
            len(raw_rows),
            failures,
        )
        check_equal(
            f"moe-raw/{model}/complete-three-seed-groups",
            all(sorted(seed_values) == claims["moe"]["seeds"] for seed_values in groups.values()),
            True,
            failures,
        )

        raw_thresholds = {}
        for policy in expected_policies:
            policy_groups = {
                rate: seed_values
                for (group_policy, rate), seed_values in groups.items()
                if group_policy == policy
            }
            check_equal(
                f"moe-raw/{model}/{policy}/grid-points",
                len(policy_groups),
                claims["moe"]["grid_points_per_policy"],
                failures,
            )
            accepted = [
                rate
                for rate, seed_values in policy_groups.items()
                if sum(seed_values.values()) / len(seed_values) >= gate
            ]
            if not accepted:
                failures.append(f"moe-raw/{model}/{policy}/no-accepted-rate")
                continue
            raw_thresholds[policy] = max(accepted)
            check_equal(
                f"moe-raw/{model}/{policy}/threshold",
                raw_thresholds[policy],
                expected_values[policy],
                failures,
            )

        if all(policy in raw_thresholds for policy in expected_policies):
            better_baseline = max(
                raw_thresholds["Lazarus-style"], raw_thresholds["FlexMoE-style"]
            )
            raw_gain = raw_thresholds["DCNC-DAG-H"] / better_baseline
            check_equal(
                f"moe-raw/{model}/gain",
                raw_gain,
                expected_values["gain"],
                failures,
            )
            paper_flexmoe = float(claims["moe"]["paper"][model]["FlexMoE-style"])
            flexmoe_grid = {
                rate for (policy, rate) in groups if policy == "FlexMoE-style"
            }
            check_equal(
                f"moe-raw/{model}/paper-flexmoe-value-in-grid",
                paper_flexmoe in flexmoe_grid,
                False,
                failures,
            )

            convention = audit["threshold_convention_checks"]["models"][model]
            flex_groups = {
                rate: seed_values
                for (policy, rate), seed_values in groups.items()
                if policy == "FlexMoE-style"
            }
            flex_means = {
                rate: sum(seed_values.values()) / len(seed_values)
                for rate, seed_values in flex_groups.items()
            }
            flex_throughput_means = {
                rate: sum(seed_values.values()) / len(seed_values)
                for (policy, rate), seed_values in throughput_groups.items()
                if policy == "FlexMoE-style"
            }
            last_accepted = max(
                rate for rate, mean in flex_means.items() if mean >= gate
            )
            first_rejected = min(
                rate
                for rate, mean in flex_means.items()
                if rate > last_accepted and mean < gate
            )
            accepted_mean = flex_means[last_accepted]
            rejected_mean = flex_means[first_rejected]
            crossing = last_accepted + (
                (gate - accepted_mean)
                * (first_rejected - last_accepted)
                / (rejected_mean - accepted_mean)
            )
            paper_rate = float(claims["moe"]["paper"][model]["FlexMoE-style"])
            lower = max(rate for rate in flex_means if rate < paper_rate)
            upper = min(rate for rate in flex_means if rate > paper_rate)
            completion_at_paper = flex_means[lower] + (
                (paper_rate - lower)
                * (flex_means[upper] - flex_means[lower])
                / (upper - lower)
            )
            rate_at_max_throughput, max_mean_throughput = max(
                flex_throughput_means.items(), key=lambda item: item[1]
            )
            throughput_at_paper = flex_throughput_means[lower] + (
                (paper_rate - lower)
                * (
                    flex_throughput_means[upper]
                    - flex_throughput_means[lower]
                )
                / (upper - lower)
            )
            seed_thresholds = {
                str(seed): max(
                    rate
                    for rate, seed_values in flex_groups.items()
                    if seed_values[seed] >= gate
                )
                for seed in claims["moe"]["seeds"]
            }
            checks = {
                "last-accepted-rate": (
                    last_accepted,
                    convention["last_accepted_rate"],
                ),
                "last-accepted-mean": (
                    accepted_mean,
                    convention["last_accepted_mean_completion"],
                ),
                "first-rejected-rate": (
                    first_rejected,
                    convention["first_rejected_rate"],
                ),
                "first-rejected-mean": (
                    rejected_mean,
                    convention["first_rejected_mean_completion"],
                ),
                "linear-crossing": (
                    crossing,
                    convention["linear_crossing_at_0.95"],
                ),
                "paper-rate-bracket": (
                    [lower, upper],
                    convention["paper_rate_bracket"],
                ),
                "completion-at-paper-rate": (
                    completion_at_paper,
                    convention["linear_mean_completion_at_paper_rate"],
                ),
                "max-mean-completed-throughput": (
                    max_mean_throughput,
                    convention["max_mean_completed_throughput"],
                ),
                "arrival-rate-at-max-mean-completed-throughput": (
                    rate_at_max_throughput,
                    convention[
                        "arrival_rate_at_max_mean_completed_throughput"
                    ],
                ),
                "completed-throughput-at-paper-rate": (
                    throughput_at_paper,
                    convention[
                        "linear_mean_completed_throughput_at_paper_rate"
                    ],
                ),
                "per-seed-thresholds": (
                    seed_thresholds,
                    convention["per_seed_0.95_thresholds"],
                ),
            }
            for label, (observed, expected) in checks.items():
                check_equal(
                    f"moe-raw/{model}/alternate/{label}",
                    observed,
                    expected,
                    failures,
                )
    print(
        "[HISTORICAL ONLY] The September PDF mismatch remains documented; "
        "the latest designated paper is checked separately."
    )


def verify_table6_protocol(claims: dict, failures: list[str]) -> None:
    historical_times = claims["table6"]["historical_pdf_seconds_per_slot"]
    path = ROOT / claims["table6"]["evidence"]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    check_equal("table6/command-matrix-sha256", digest, claims["table6"]["command_matrix_sha256"], failures)
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    check_equal("table6/job-count", len(rows), claims["table6"]["expected_jobs"], failures)
    check_equal("table6/seeds", sorted({int(r["seed"]) for r in rows}), claims["table6"]["seeds"], failures)
    check_equal("table6/slots", sorted({int(r["slots"]) for r in rows}), [claims["table6"]["slots"]], failures)
    check_equal("table6/solver", sorted({r["solver"] for r in rows}), [claims["table6"]["solver"]], failures)

    fingerprint = json.loads(
        (ROOT / claims["table6"]["runtime_fingerprint"]).read_text(encoding="utf-8")
    )
    for relative, expected_hash in fingerprint["release_file_sha256"].items():
        observed_hash = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        check_equal(
            f"table6/runtime-hash/{relative}",
            observed_hash,
            expected_hash,
            failures,
        )
    remote_to_release = {
        "tools/dynvmp_bridge.py": "tools/dynvmp_bridge.py",
        "tools/run_dynvmp_bridge.sh": (
            "evidence/table6/runtime/run_dynvmp_bridge.remote.sh"
        ),
        "scripts/run_edge_experiments.py": "scripts/run_edge_experiments.py",
        "experiments/k_runtime/k_runtime_main_commands_100000slots_seed123_20260927.csv": (
            "evidence/table6/commands.csv"
        ),
    }
    for remote_name, release_name in remote_to_release.items():
        check_equal(
            f"table6/runtime-remote-match/{remote_name}",
            fingerprint["remote_executed_sha256"][remote_name],
            fingerprint["release_file_sha256"][release_name],
            failures,
        )
    check_equal(
        "table6/runtime/core-bridge-identical",
        fingerprint["wrapper_relationship"]["core_bridge_bytes_identical"],
        True,
        failures,
    )
    for source_name in ("alib", "vnep_approx"):
        source_audit = fingerprint["third_party_source_audit"][source_name]
        check_equal(
            f"table6/runtime/{source_name}/common-files",
            source_audit["common_files"],
            source_audit["release_source_files"],
            failures,
        )
        check_equal(
            f"table6/runtime/{source_name}/mismatched-files",
            source_audit["mismatched_common_files"],
            0,
            failures,
        )
        check_equal(
            f"table6/runtime/{source_name}/release-only-files",
            source_audit["release_only_files"],
            0,
            failures,
        )

    audit = json.loads(
        (ROOT / claims["table6"]["timing_audit"]).read_text(encoding="utf-8")
    )
    check_equal(
        "table6/timing-audit/status",
        audit["status"],
        "paper-timing-mismatch",
        failures,
    )
    check_equal(
        "table6/timing-audit/paper-sha256",
        audit["paper_source"]["sha256"],
        claims["table6"]["historical_pdf_sha256"],
        failures,
    )
    check_equal(
        "table6/timing-audit/paper-horizon",
        audit["paper_source"]["horizon"],
        claims["table6"]["slots"],
        failures,
    )
    check_equal(
        "table6/timing-audit/paper-seeds",
        audit["paper_source"]["seeds"],
        claims["table6"]["seeds"],
        failures,
    )
    check_equal(
        "table6/timing-audit/paper-calls",
        audit["paper_source"]["calls"],
        claims["table6"]["paper_calls"],
        failures,
    )
    check_equal(
        "table6/timing-audit/paper-seconds-per-slot",
        audit["paper_source"]["seconds_per_slot"],
        historical_times,
        failures,
    )

    intermediate = audit["manuscript_intermediate"]
    check_equal(
        "table6/timing-audit/intermediate-path",
        intermediate["evidence"],
        claims["table6"]["manuscript_intermediate_evidence"],
        failures,
    )
    intermediate_path = ROOT / claims["table6"]["manuscript_intermediate_evidence"]
    intermediate_digest = hashlib.sha256(intermediate_path.read_bytes()).hexdigest()
    check_equal(
        "table6/timing-audit/intermediate-sha256",
        intermediate_digest,
        intermediate["source_sha256"],
        failures,
    )
    topology_cases = {"Milan": "driving_milan", "Random": "driving_random"}
    intermediate_rows = {}
    for line in intermediate_path.read_text(encoding="utf-8").splitlines():
        if not any(line.startswith(f"| {name}") for name in topology_cases):
            continue
        columns = [column.strip() for column in line.strip().strip("|").split("|")]
        topology, fixed_k_text, lambda_text, calls_text, timing_text = columns
        timing_value, timing_unit = timing_text.split()
        seconds_per_slot = float(timing_value)
        if timing_unit == "ms":
            seconds_per_slot /= 1000.0
        elif timing_unit != "s":
            failures.append(f"table6/timing-audit/intermediate-unit/{timing_unit}")
            continue
        key = (topology_cases[topology], int(fixed_k_text))
        intermediate_rows[key] = {
            "lambda_hat": float(lambda_text),
            "calls": float(calls_text),
            "seconds_per_slot": seconds_per_slot,
        }

    expected_intermediate = {
        (row["case"], int(row["fixed_k"])): row
        for row in intermediate["rows"]
    }
    expected_keys = {
        (case, fixed_k)
        for case in ("driving_milan", "driving_random")
        for fixed_k in (1, 4, 16, 64, 256)
    }
    check_equal(
        "table6/timing-audit/intermediate-row-keys",
        set(intermediate_rows),
        expected_keys,
        failures,
    )
    check_equal(
        "table6/timing-audit/intermediate-expected-row-keys",
        set(expected_intermediate),
        expected_keys,
        failures,
    )
    intermediate_timing_ratios = defaultdict(list)
    intermediate_call_differences = defaultdict(list)
    for case, fixed_k in sorted(expected_keys):
        parsed = intermediate_rows[(case, fixed_k)]
        expected = expected_intermediate[(case, fixed_k)]
        for field in ("lambda_hat", "calls", "seconds_per_slot"):
            check_equal(
                f"table6/timing-audit/intermediate/{case}/K={fixed_k}/{field}",
                parsed[field],
                expected[field],
                failures,
                tol=1e-12,
            )
        paper_timing = float(
            historical_times[case][str(fixed_k)]
        )
        paper_calls = float(claims["table6"]["paper_calls"][case][str(fixed_k)])
        intermediate_timing_ratios[case].append(
            paper_timing / parsed["seconds_per_slot"]
        )
        intermediate_call_differences[case].append(
            (paper_calls - parsed["calls"]) / parsed["calls"]
        )

    relationship = intermediate["relationship_to_paper"]
    for case, expected_ratio in (("driving_milan", 1.0), ("driving_random", 2.0)):
        values = intermediate_timing_ratios[case]
        observed = {
            "timing_ratio_mean": sum(values) / len(values),
            f"max_abs_timing_ratio_deviation_from_{'one' if expected_ratio == 1.0 else 'two'}": max(
                abs(value - expected_ratio) for value in values
            ),
            "max_abs_call_relative_difference": max(
                abs(value) for value in intermediate_call_differences[case]
            ),
        }
        for field, value in observed.items():
            check_equal(
                f"table6/timing-audit/intermediate-relationship/{case}/{field}",
                value,
                relationship[case][field],
                failures,
                tol=1e-12,
            )

    legacy_path = ROOT / claims["table6"]["legacy_20k_evidence"]
    legacy_digest = hashlib.sha256(legacy_path.read_bytes()).hexdigest()
    check_equal(
        "table6/timing-audit/legacy-sha256",
        legacy_digest,
        audit["legacy_20k_campaign"]["remote_source_sha256"],
        failures,
    )
    with legacy_path.open(newline="", encoding="utf-8") as handle:
        legacy_rows = list(csv.DictReader(handle))
    legacy_by_key = {
        (row["case"], int(row["fixed_k"])): row for row in legacy_rows
    }
    check_equal(
        "table6/timing-audit/legacy-row-keys",
        set(legacy_by_key),
        expected_keys,
        failures,
    )
    for key, row in legacy_by_key.items():
        expected_runs, expected_rates = (
            (5, 2) if key == ("driving_random", 256) else (15, 5)
        )
        check_equal(
            f"table6/timing-audit/legacy/{key[0]}/K={key[1]}/runs",
            int(row["num_runs"]),
            expected_runs,
            failures,
        )
        check_equal(
            f"table6/timing-audit/legacy/{key[0]}/K={key[1]}/rates",
            int(row["num_rates"]),
            expected_rates,
            failures,
        )

    comparison = {
        (row["case"], int(row["fixed_k"])): row
        for row in audit["paper_to_legacy_comparison"]
    }
    check_equal(
        "table6/timing-audit/comparison-row-keys",
        set(comparison),
        expected_keys,
        failures,
    )
    recomputed_ratios: dict[tuple[str, int], float] = {}
    for case, fixed_k in sorted(expected_keys):
        legacy = legacy_by_key[(case, fixed_k)]
        legacy_per_slot = (
            float(legacy["mean_dynvmp_wall_time_sec"])
            / float(audit["legacy_20k_campaign"]["horizon"])
        )
        paper_per_slot = float(
            historical_times[case][str(fixed_k)]
        )
        ratio = paper_per_slot / legacy_per_slot
        recomputed_ratios[(case, fixed_k)] = ratio
        item = comparison[(case, fixed_k)]
        check_equal(
            f"table6/timing-audit/{case}/K={fixed_k}/legacy-per-slot",
            legacy_per_slot,
            item["legacy_seconds_per_slot"],
            failures,
            tol=1e-12,
        )
        check_equal(
            f"table6/timing-audit/{case}/K={fixed_k}/paper-per-slot",
            paper_per_slot,
            item["paper_seconds_per_slot"],
            failures,
            tol=1e-12,
        )
        check_equal(
            f"table6/timing-audit/{case}/K={fixed_k}/ratio",
            ratio,
            item["paper_to_legacy_ratio"],
            failures,
            tol=1e-12,
        )

    def verify_ratio_summary(label: str, values: list[float], expected: dict) -> None:
        mean = sum(values) / len(values)
        sample_variance = sum((value - mean) ** 2 for value in values) / (
            len(values) - 1
        )
        sample_sd = math.sqrt(sample_variance)
        maximum_relative_deviation = max(
            abs(value / mean - 1.0) for value in values
        )
        observed = {
            "mean": mean,
            "sample_standard_deviation": sample_sd,
            "coefficient_of_variation": sample_sd / mean,
            "maximum_relative_deviation_from_mean": maximum_relative_deviation,
        }
        for field, value in observed.items():
            check_equal(
                f"table6/timing-audit/ratio-summary/{label}/{field}",
                value,
                expected[field],
                failures,
                tol=1e-12,
            )

    verify_ratio_summary(
        "milan",
        [
            recomputed_ratios[("driving_milan", fixed_k)]
            for fixed_k in (1, 4, 16, 64, 256)
        ],
        audit["ratio_summary"]["driving_milan_all_k"],
    )
    verify_ratio_summary(
        "random-complete-five-rate-rows",
        [
            recomputed_ratios[("driving_random", fixed_k)]
            for fixed_k in (1, 4, 16, 64)
        ],
        audit["ratio_summary"]["driving_random_complete_five_rate_rows_k_1_to_64"],
    )
    current_campaign = audit["current_100k_campaign"]
    check_equal(
        "table6/timing-audit/current-campaign/jobs",
        current_campaign["jobs"],
        claims["table6"]["expected_jobs"],
        failures,
    )
    check_equal(
        "table6/timing-audit/current-campaign/horizon",
        current_campaign["horizon"],
        claims["table6"]["slots"],
        failures,
    )
    check_equal(
        "table6/timing-audit/current-campaign/seeds",
        current_campaign["seeds"],
        claims["table6"]["seeds"],
        failures,
    )
    check_equal(
        "table6/timing-audit/current-campaign/scheduler-panes",
        current_campaign["scheduler_panes"],
        fingerprint["campaign"]["scheduler_panes"],
        failures,
    )
    print(
        "[HISTORICAL ONLY] The old PDF timing mismatch remains archived. "
        "The corrected paper project is verified independently against all 150 runs."
    )

    progress_path = ROOT / claims["table6"]["progress_evidence"]
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    observed_total = sum(
        int(progress[name]) for name in ("completed", "running", "queued", "failed")
    )
    check_equal(
        "table6/progress-job-total",
        observed_total,
        claims["table6"]["expected_jobs"],
        failures,
    )
    check_equal(
        "table6/progress-failed",
        int(progress["failed"]),
        0,
        failures,
    )
    check_equal(
        "table6/progress-error-pattern-files",
        int(progress["error_pattern_files"]),
        0,
        failures,
    )
    check_equal("table6/progress-final", bool(progress["final"]), True, failures)
    check_equal("table6/campaign-status", claims["table6"]["campaign_status"], "complete", failures)
    check_equal("table6/status", claims["table6"]["status"], "exact-at-paper-precision", failures)
    check_equal(
        "table6/timing-status", claims["table6"]["timing_status"],
        "exact-source-provenance", failures,
    )
    try:
        verified = verify_results(ROOT, claims["table6"])
    except (OSError, ValueError, KeyError, TypeError) as error:
        failures.append("table6/imported-results")
        print(f"[FAIL] table6/imported-results: {error}")
    else:
        print(f"[PASS] table6/imported-results: {verified}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Fail on known pending/mismatch release gates.")
    parser.add_argument("--paper-project", type=Path, help="Also verify the updated source ZIP and its excerpts.")
    parser.add_argument(
        "--paper",
        type=Path,
        help=(
            "Also require this PDF to match the paper SHA-256 pinned in the "
            "claims manifest."
        ),
    )
    args = parser.parse_args()
    manifest = json.loads(CLAIMS_PATH.read_text(encoding="utf-8"))
    claims = manifest["claims"]
    failures: list[str] = []

    verify_manifest_metadata(manifest, failures)
    if args.paper is not None:
        verify_external_paper(manifest, args.paper, failures)
    verify_lp(claims, failures)
    verify_main_thresholds(claims, failures)
    verify_frame_length(claims, failures)
    verify_workflow(claims, failures)
    verify_fifo(claims, failures)
    verify_moe(claims, failures)
    verify_table6_protocol(claims, failures)
    try:
        print(f"[PASS] updated-paper-project: {verify_update(ROOT, args.paper_project)}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        failures.append("updated-paper-project")
        print(f"[FAIL] updated-paper-project: {error}")

    if failures:
        print(f"\nClaim verification failed: {len(failures)} check(s).", file=sys.stderr)
        return 1
    if args.strict and not manifest["release_ready"]:
        print("\nStrict release gate failed: release_ready is false.", file=sys.stderr)
        for gate in manifest["open_gates"]:
            print(f"  - {gate}", file=sys.stderr)
        return 2
    print("\nAll included evidence is internally consistent with its declared status.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
