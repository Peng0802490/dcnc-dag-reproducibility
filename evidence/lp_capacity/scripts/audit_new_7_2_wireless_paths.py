#!/usr/bin/env python3
"""Independently audit the Section 7.2 IID wireless sample paths.

The formal simulator draws one wireless state while constructing its physical
network and then one state per simulated slot. This audit reproduces that call
order, excludes the construction draw, and checks the resulting paths against
the hashes and edge marginals recorded by the formal campaign.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections import Counter
from itertools import combinations, product
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2

from run_new_7_2_wireless_mixed_mapping import (
    AuditedIIDOnOffProcess,
    DYNAMIC_EDGES,
    make_case,
)


def edge_column(edge: tuple[str, str]) -> str:
    return "on_fraction_{}->{}".format(edge[0], edge[1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--formal-runs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--slots", type=int, default=100_000)
    parser.add_argument("--seeds", type=int, default=5)
    args = parser.parse_args()
    if os.environ.get("PYTHONHASHSEED") != "0":
        parser.error("launch with PYTHONHASHSEED=0 to match the formal campaign")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    formal = pd.read_csv(args.formal_runs)
    all_samples = []
    state_counts: Counter[tuple[int, ...]] = Counter()
    seed_rows = []

    for seed in range(args.seeds):
        case = make_case("mixed")
        wireless = AuditedIIDOnOffProcess(
            case.network, case.dynamic_edge_p_on, seed=10_000 + 101 * seed
        )

        # Mirror PhysicalNetwork.__init__, whose first draw initializes current
        # capacities but is not part of the total_slots recorded trajectory.
        wireless.sample_capacities(-1)
        samples = np.empty((args.slots, len(DYNAMIC_EDGES)), dtype=np.uint8)
        for slot in range(args.slots):
            capacities = wireless.sample_capacities(slot)
            bits = tuple(int(float(capacities[edge]) > 0.0) for edge in DYNAMIC_EDGES)
            samples[slot, :] = bits
            state_counts[bits] += 1

        if wireless.sample_calls != args.slots + 1:
            raise AssertionError("wireless sample call count differs from simulator contract")

        formal_seed = formal[formal["seed"] == seed]
        formal_hashes = formal_seed["wireless_path_sha256"].drop_duplicates().tolist()
        if len(formal_hashes) != 1 or formal_hashes[0] != wireless.run_path_sha256():
            raise AssertionError("wireless path hash mismatch for seed {}".format(seed))

        row = {
            "seed": seed,
            "slots": args.slots,
            "wireless_path_sha256": wireless.run_path_sha256(),
        }
        for index, edge in enumerate(DYNAMIC_EDGES):
            observed = float(samples[:, index].mean())
            recorded = formal_seed[edge_column(edge)].drop_duplicates().to_numpy(dtype=float)
            if len(recorded) != 1 or not math.isclose(
                observed, float(recorded[0]), rel_tol=0.0, abs_tol=1e-12
            ):
                raise AssertionError(
                    "wireless marginal mismatch for seed {} edge {}".format(seed, edge)
                )
            row[edge_column(edge)] = observed
        seed_rows.append(row)
        all_samples.append(samples)

    combined = np.concatenate(all_samples, axis=0)
    p_on = 0.85
    count_rows = []
    chi_square = 0.0
    for state in product((0, 1), repeat=len(DYNAMIC_EDGES)):
        on_count = sum(state)
        probability = (p_on**on_count) * ((1.0 - p_on) ** (len(state) - on_count))
        expected = len(combined) * probability
        observed = int(state_counts[state])
        chi_square += (observed - expected) ** 2 / expected
        count_rows.append(
            {
                "state": "".join(str(bit) for bit in state),
                "observed_count": observed,
                "observed_fraction": observed / len(combined),
                "expected_probability": probability,
                "expected_count": expected,
                "standardized_residual": (observed - expected) / math.sqrt(expected),
            }
        )

    correlations = {}
    for left, right in combinations(range(len(DYNAMIC_EDGES)), 2):
        name = "edge_{}_edge_{}".format(left + 1, right + 1)
        correlations[name] = float(np.corrcoef(combined[:, left], combined[:, right])[0, 1])

    marginal_fractions = {
        "edge_{}:{}->{}".format(index + 1, edge[0], edge[1]): float(
            combined[:, index].mean()
        )
        for index, edge in enumerate(DYNAMIC_EDGES)
    }
    p_value = float(chi2.sf(chi_square, (2 ** len(DYNAMIC_EDGES)) - 1))
    max_marginal_error = max(abs(value - p_on) for value in marginal_fractions.values())
    max_abs_correlation = max(abs(value) for value in correlations.values())

    # These are broad implementation-error guards, not acceptance tests for a
    # particular random realization. Exact path hashes provide the strict audit.
    if len(state_counts) != 16:
        raise AssertionError("not all 16 configured wireless states were observed")
    if max_marginal_error >= 0.01:
        raise AssertionError("wireless marginal differs from p_on by at least 0.01")
    if max_abs_correlation >= 0.01:
        raise AssertionError("wireless edge correlation magnitude is at least 0.01")

    pd.DataFrame(seed_rows).to_csv(args.output_dir / "wireless_seed_paths.csv", index=False)
    pd.DataFrame(count_rows).to_csv(
        args.output_dir / "wireless_joint_state_counts.csv", index=False
    )
    report = {
        "passed": True,
        "slots_per_seed": args.slots,
        "seed_count": args.seeds,
        "total_slot_samples": int(len(combined)),
        "dynamic_edge_order": [list(edge) for edge in DYNAMIC_EDGES],
        "configured_p_on": p_on,
        "all_16_states_observed": len(state_counts) == 16,
        "marginal_on_fractions": marginal_fractions,
        "max_absolute_marginal_error": max_marginal_error,
        "pairwise_pearson_correlations": correlations,
        "max_absolute_pairwise_correlation": max_abs_correlation,
        "pearson_chi_square": chi_square,
        "degrees_of_freedom": 15,
        "chi_square_p_value": p_value,
        "interpretation": (
            "Path hashes and per-seed marginals exactly match the formal campaign; "
            "the distributional statistics are diagnostic checks of the configured "
            "independent Bernoulli(0.85) edge process."
        ),
    }
    (args.output_dir / "wireless_path_audit.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
