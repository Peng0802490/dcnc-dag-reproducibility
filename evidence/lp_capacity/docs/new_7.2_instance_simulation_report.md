# New Section 7.2 Instance - Final Simulation and Audit Report

Date: 2026-07-23

## 1. Final conclusion

The wireless mixed-mapping fork-join instance is internally consistent and
exhibits the intended behavior under the actual DCNC-DAG implementation.

- Three capacity calculations agree on `lambda*=1.000000`: the simulator's
  Gurobi LP, the simulator's SciPy LP, and a simulator-independent SciPy LP.
- The boundary solution is uniquely `f_m1=f_m2=0.5`; either mapping alone has
  capacity `0.5`.
- With computation constraints removed and equal mapping rates enforced, the
  wireless/primary-interference capacity is `1.428571`, so wireless resources
  have 42.86% headroom at `lambda=1` and do not set the boundary.
- DCNC-DAG learns a near-50/50 request mixture without receiving the LP rates.
- The fixed-`m1` ablation tracks arrivals below `0.5` and saturates at `0.5`.
- Using the corrected workload definition and the fixed strict cutoff
  `slope > 0.05`, the first tested overloaded rate flagged in all five seeds is
  `lambda=1.05`. The operational resolution on this grid is therefore 5%
  beyond the LP boundary.

The earlier 3% figure is not a valid workload-based result. It came from the
simulator's `total_backlog()`, which counts queue objects. The correction is
fully documented in `new_7.2_instance_simulation_correction_log.md`.

## 2. Exact instance and capacity audit

The audit of the actual simulator object verifies all 7 substrate nodes, 8
directed links, node/link capacities, four dynamic links with `p_on=0.85`, DAG
workloads, endpoint pins, candidate sets, and per-mapping load vectors. It
finds exactly two mappings and exactly 16 wireless states. The numbers of
feasible primary-interference activation sets in those states are

```
8, 11, 11, 14, 11, 14, 15, 18,
11, 15, 14, 18, 14, 18, 18, 22,
```

for 232 state-activation variables in total.

| Capacity calculation | Capacity | `f_m1` | `f_m2` |
|---|---:|---:|---:|
| Actual instance, Gurobi | 1.000000 | 0.500000 | 0.500000 |
| Actual instance, SciPy | 1.000000 | 0.500000 | 0.500000 |
| Independent full LP | 1.000000 | 0.500000 | 0.500000 |
| Only `m1` allowed | 0.500000 | 0.500000 | 0 |
| Only `m2` allowed | 0.500000 | 0 | 0.500000 |
| Wireless only, equal mixture | 1.428571 | 0.714286 | 0.714286 |

The computation constraints imply `f_m1<=0.5` and `f_m2<=0.5`. Hence any
solution with `f_m1+f_m2=1` must have `f_m1=f_m2=0.5`; uniqueness is analytic,
not an inference from rounded solver output.

## 3. Canonical protocol

The canonical campaign contains 95 runs of 100,000 slots:

- main policy: 7 rates x 5 seeds = 35 runs;
- fixed-`m1` ablation: 12 rates x 5 seeds = 60 runs;
- logical seeds: `0,1,2,3,4`;
- bounded arrivals: `floor(lambda)+Bernoulli(frac(lambda))`;
- empty initial state, `T_f=1`, exact mapping enumeration, NTO physical
  scheduling, IID ON/OFF links, and primary interference;
- `PYTHONHASHSEED=0`, required by the driver for deterministic equal-weight
  NetworkX matching ties;
- identical arrival and wireless paths for paired main/ablation runs.
- exact incremental physical measurement in integer `0.1`-workload units; 64
  rows were cross-checked against full per-slot queue scans before acceptance.

All means below are five-seed means. Parentheses contain standard errors,
computed as the sample standard deviation divided by `sqrt(5)`.

## 4. Main sweep

| Offered rate | Completed throughput | Completion ratio | Request share `m1` |
|---:|---:|---:|---:|
| 0.95 | 0.949596 (0.000319) | 0.999874 (0.000007) | 0.505225 (0.000072) |
| 0.98 | 0.979740 (0.000150) | 0.999851 (0.000011) | 0.502391 (0.000044) |
| 0.99 | 0.989662 (0.000207) | 0.999853 (0.000007) | 0.501336 (0.000032) |
| 1.01 | 0.999876 (0.000005) | 0.990112 (0.000219) | 0.500003 (0.000002) |
| 1.03 | 0.999858 (0.000008) | 0.970484 (0.000320) | 0.500002 (0.000001) |
| 1.05 | 0.999860 (0.000011) | 0.952013 (0.000424) | 0.500002 (0.000001) |
| 1.10 | 0.999882 (0.000010) | 0.909058 (0.000326) | 0.500003 (0.000002) |

The maximum standard errors in this table are `3.19e-4` for throughput,
`4.24e-4` for completion ratio, and `7.17e-5` for mapping share. The share is
arrival-weighted: if a bounded-arrival slot contains two requests, its selected
mapping receives weight two. This is the requested fraction of arriving
requests, not merely the fraction of mapping-solver calls.

The subcritical points track offered load with completion ratios above
`0.99985`. Above the boundary, output remains approximately one while the
completion ratio decreases. Request-level `m1` shares range from `0.500002` to
`0.505225`, consistent with recovery of the unique equal mixture.

## 5. Backlog diagnostics

The paper-facing physical workload is

```
remaining link workload
+ remaining compute workload
+ payload workload already held in synchronization pools.
```

The virtual quantity is the sum of virtual link and node workloads. The
combined flag is true when either workload slope is strictly greater than
`0.05`. Object counts are shown only to make the correction auditable.

| Rate | Object-count slope | Object flags | Physical workload slope | Physical flags | Virtual workload slope | Virtual flags | Combined flags |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.95 | -0.0000012 | 0/5 | -0.0000007 | 0/5 | -0.0000002 | 0/5 | 0/5 |
| 0.98 | -0.0000005 | 0/5 | -0.0000005 | 0/5 | 0.0000009 | 0/5 | 0/5 |
| 0.99 | 0.0000052 | 0/5 | 0.0000032 | 0/5 | 0.0000008 | 0/5 | 0/5 |
| 1.01 | 0.0198490 | 0/5 | 0.0119094 | 0/5 | 0.0099238 | 0/5 | 0/5 |
| 1.03 | 0.0601150 | 5/5 | 0.0360690 | 0/5 | 0.0300567 | 0/5 | 0/5 |
| 1.05 | 0.1000576 | 5/5 | 0.0600345 | 5/5 | 0.0500286 | 2/5 | 5/5 |
| 1.10 | 0.2004913 | 5/5 | 0.1202946 | 5/5 | 0.1002463 | 5/5 | 5/5 |

Thus `1.03` is correctly unflagged by both workload metrics even though the
object-count sensitivity measure crosses. At `1.05`, the physical workload
crosses in all five seeds; the virtual mean is slightly above the cutoff but
only two individual seeds cross, which is why the combined all-seed conclusion
rests on the physical workload there.

## 6. Fixed-mapping ablation

The points around the single-mapping boundary show the expected knee:

| Offered rate | Completed throughput | Completion ratio | Combined flags |
|---:|---:|---:|---:|
| 0.45 | 0.450278 | 0.999893 | 0/5 |
| 0.49 | 0.490350 | 0.999821 | 0/5 |
| 0.50 | 0.499140 | 0.997408 | 0/5 |
| 0.51 | 0.499832 | 0.979492 | 0/5 |
| 0.55 | 0.499938 | 0.908788 | 5/5 |

At offered rate `0.99`, the canonical fixed-`m1` values are:

- completed throughput: `0.499968`;
- throughput standard error: `0.00000374`;
- completion ratio: `0.505116`.

The lack of a flag at `0.51` is not evidence of stability. It means only that a
1% overload does not cross the fixed `0.05` slope cutoff within the stated
finite-horizon diagnostic. The throughput and completion-ratio knee identify
the single-mapping capacity independently.

## 7. Wireless path audit

An independent replay used the simulator's exact initialization and per-slot
draw order and matched every formal per-seed wireless SHA-256 and edge
marginal. Across 500,000 audited slot samples:

- all 16 joint states were observed;
- marginal ON fractions were `0.850240`, `0.849556`, `0.850336`, and
  `0.848866` in the specified edge order;
- maximum absolute marginal error from `0.85` was `0.001134`;
- maximum absolute pairwise Pearson correlation was `0.002869`;
- the 16-cell Pearson goodness-of-fit statistic was `16.7465` on 15 degrees of
  freedom (`p=0.3342`).

These sample statistics are diagnostics, not a proof of independence. The IID
claim is grounded in the configured `IIDOnOffProcess`; the diagnostics show no
contradiction in the realized canonical paths.

## 8. Independent reproduction and integrity

All 35 main runs were independently rerun with separate passive metric
instrumentation. The following quantities match the formal campaign exactly
for every rate and seed: arrivals, completions, throughput, completion ratio,
mapping calls, request/call mapping shares, arrival path hash, wireless path
hash, object-count slope, corrected physical workload slope, and virtual
workload slope. The maximum numeric difference for each compared numeric field
is zero.

The incremental physical observer was separately compared with a full-scan
reference for 64 completed 100,000-slot rows. All behavior fields, path hashes,
object-count slopes, and virtual-workload slopes match exactly. The maximum
physical-workload slope difference is `4.8073e-14`, caused only by floating
point summation order and below the predeclared `1e-12` tolerance.

Machine-readable evidence is stored at:

- canonical raw data and aggregation:
  `results_new_7_2_validation_20260723/canonical/`;
- independent capacity audit:
  `results_new_7_2_validation_20260723/capacity_lp_audit.json`;
- actual-instance contract audit:
  `results_new_7_2_validation_20260723/instance_contract/`;
- deterministic second pass:
  `results_new_7_2_validation_20260723/second_pass_canonical/`;
- wireless path audit:
  `results_new_7_2_validation_20260723/wireless_path_audit/`.
- incremental/full-scan observer validation:
  `results_new_7_2_validation_20260723/observer_validation/`.

The delivery archive contains per-file SHA-256 values. The second-pass report
also records SHA-256 values for the eight exercised `dcnc_sim` source modules.

## 9. Claim boundary

The exact LP establishes the capacity and forced mixture for the specified
finite instance. The simulations verify the implemented algorithm's behavior
over the declared 100,000-slot, five-seed, discrete-rate campaign. They do not
constitute a general proof of stochastic stability or identify an exact
continuous-valued detection threshold. The precise defensible statement is:

> On the tested grid, the corrected workload diagnostic first flags overload
> in all five seeds at 1.05, while 1.03 is unflagged.
