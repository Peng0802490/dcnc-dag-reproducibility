# FIFO / NTO backlog-timeline campaign

Generated 2026-09-17.

## 1. Simulator snapshot

`FIFO_sawtooth_audit_20260727/code/sim_exact.py`, the simulator behind the
current Section 7.4.2 / Fig. 6 results. Two additive changes were made across
this round and the preceding robustness round, both recording extra counters at
points the simulator already visits:

- `segment_arrivals`: cumulative arrivals at each segment boundary;
- `smp_arrivals`: cumulative arrivals at each `sample_every` sample.

No scheduling, workload, capacity, mapping or arrival logic was touched. The
unmodified file is kept as `sim_exact.py.orig`. Archived runs reproduce
bit-identically in `completed`, `arrivals_total` and `final_backlog`.

## 2. Command lines

```
cd FIFO_sawtooth_audit_20260727/code
BACKLOG_WORKERS=60 python run_backlog_experiments.py AB   # experiments A and B
python aggregate_backlog_results.py                       # aggregates + sanity checks
python plot_backlog_results.py                            # all figures
```

## 3. Seeds

Experiment A: `{1,...,20}`. Experiment B: the first ten of the same set,
`{1,...,10}`. Streams come from `np.random.SeedSequence(seed).spawn(3)`, with
the `arrival` child used for arrivals.

## 4. Arrival rates

Experiment A: 0.50, 0.60, 0.70, 0.76, 0.80, 0.85, 0.90, 0.95

Experiment B: 0.70, 0.80, 0.90

`0.98` is not in the sweep, as instructed.

## 5. Horizon and sampling

| experiment | horizon | sampling interval | samples per run |
|---|---:|---:|---:|
| A | 2,000,000 | 2,000 | 1001 (1000 sampled slots plus the horizon) |
| B | 10,000,000 | 10,000 | 1001 |

## 6. Initial condition

`B0 = 0` in every run of both experiments: all queues start empty and the
first requests enter only through the arrival process. The `B0=500` preload of
the earlier campaign is not used here.

## 7. FIFO / NTO arrival coupling

Confirmed. `arrival_indicators(T, lam, seed, process)` takes no policy
argument, so a given `(seed, lambda)` produces one arrival realisation that
both policies consume. Check 11.3 compares the realised arrival totals of the
two policies in every cell and passes.

## 8. Nested common random numbers across rates

Confirmed, and already the behaviour of the existing simulator: one uniform
per slot is drawn from a lambda-independent stream and thresholded,
`A(t) = 1{u_t < lambda}`. Check 11.2 regenerates the indicator arrays for all
twenty seeds across all eight rates and verifies the monotonicity pointwise.

## 9. Slot timing convention

A sample is written after every event of slot `t` is resolved (arrivals,
service, link transfers, completions), and is reported at `time = t + 1`, that
is, the number of slots elapsed. Samples are taken at `t = 0, dt, 2dt, ...`,
and one final sample at `time = T` is appended from the run totals so that the
horizon itself always appears. `completed_throughput` divides by this `time`.
The same convention is used for FIFO and NTO.

## 10. Jobs in service

Included. `stage_X_count` is the simulator's live `stage_count`, in which a
request leaves a stage only when that stage's service completes, so a partially
served request is still counted at its current stage. The derived
`unfinished_workload_*` columns multiply those counts by the per-stage
workloads, so they follow the same convention. A cross-check that the six stage
counts sum exactly to `I(t)` at every sampled point is in the sanity report.

## 11. Sanity checks

```
FIFO/NTO backlog-timeline sanity checks
==============================================================

11.1 arrival-rate check  A_cum(T)/T ~= lambda
     maximum |A_cum(T)/T - lambda| over 380 runs: 0.000764

11.2 nested arrivals across rates (per seed, full indicator arrays)
     checked seeds 1-20 over all 8 rates on the first 2e5 slots
     result: PASS

11.3 FIFO/NTO arrival coupling
     compared 190 (experiment, lambda, seed) cells
     result: PASS

11.4 backlog identity  I(t) = A_cum(t) - kappa(t)  with B0 = 0
     maximum discrepancy over 380380 sampled points: 0

11.5 capacity boundary
     u1 load per request = 0.01 + 0.99 = 1.00
     v1 load per request = 0.99 + 0.01 + 0.01 + 0.01 = 1.02
     lambda* = min(1/1.00, 1/1.02) = 0.980392
     workloads and placement unchanged (WORK_DEFAULT, STAGE_NODE)

extra: I(t) equals the sum of the six stage counts at every sampled point
     maximum discrepancy: 0
```

## 12. Deviations from the requirements document

None affecting the model. Two notes:

- Section 6.4 asks for unfinished workload if directly available. It is not a
  stored simulator quantity, but it is an exact function of the recorded stage
  counts, so it is computed in post-processing rather than by changing the
  simulator.
- Section 6.5 stage-level data were already exposed by the existing
  `sample_every` mechanism, so the optional C1 figures are delivered.

## Candidate rate table (requirements section 12)

| lambda | NTO final | FIFO final | FIFO/NTO | NTO slope | FIFO slope | FIFO slope 95% CI | NTO cr | FIFO cr | FIFO frac. positive slope |
|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| 0.50 | 4.7 | 3.7 | 1 | -6.42e-09 | 1.036e-08 | [-8.54e-08, 1.06e-07] | 1.0000 | 1.0000 | 0.45 |
| 0.60 | 6.0 | 4.4 | 1 | 3.18e-08 | 4.058e-08 | [-6.95e-08, 1.51e-07] | 1.0000 | 1.0000 | 0.60 |
| 0.70 | 10.2 | 5.4 | 1 | 1.50e-07 | 5.736e-08 | [-4.03e-08, 1.55e-07] | 1.0000 | 1.0000 | 0.65 |
| 0.76 | 13.3 | 11190.5 | 838 | 1.91e-07 | 9.591e-03 | [-1.05e-02, 2.97e-02] | 1.0000 | 0.9926 | 0.70 |
| 0.80 | 17.4 | 278225.0 | 15944 | -5.42e-08 | 1.633e-01 | [1.13e-01, 2.13e-01] | 1.0000 | 0.8261 | 0.80 |
| 0.85 | 26.4 | 527678.4 | 19950 | -2.13e-07 | 3.140e-01 | [2.53e-01, 3.75e-01] | 1.0000 | 0.6896 | 1.00 |
| 0.90 | 43.0 | 575724.1 | 13389 | 2.50e-07 | 2.464e-01 | [1.52e-01, 3.40e-01] | 1.0000 | 0.6802 | 1.00 |
| 0.95 | 113.8 | 542243.8 | 4765 | -9.89e-07 | 1.960e-01 | [1.05e-01, 2.87e-01] | 0.9999 | 0.7146 | 0.95 |

Slopes are least-squares fits of `I(t)` over the last half of the horizon, in
requests per slot. They are descriptive finite-horizon statistics, not
stability exponents.

## Long-horizon check (experiment B, T = 1e7, 10 seeds)

| lambda | NTO final backlog | FIFO final backlog | NTO slope | FIFO slope | FIFO frac. positive slope |
|---:|---:|---:|---:|---:|---:|
| 0.70 | 9.9 | 5.6 | -1.67e-08 | 1.176e-08 | 0.40 |
| 0.80 | 16.8 | 1915175.8 | -5.42e-08 | 2.351e-01 | 1.00 |
| 0.90 | 45.8 | 2967597.3 | -2.32e-08 | 2.518e-01 | 1.00 |

## Observations (factual only)

1. There is a sharp change between `lambda = 0.70` and `lambda = 0.76`. At
   `0.50`, `0.60` and `0.70` the FIFO mean final backlog is single digit and is
   in fact *below* the NTO value; from `0.76` upward it is three to five orders
   of magnitude larger.
2. NTO's mean final backlog stays between 4.7 and 113.8 across all eight rates,
   with last-half slopes of order 1e-7 and of both signs.
3. At `lambda = 0.85` and `0.90` every one of the twenty seeds has a positive
   FIFO slope; at `0.95` nineteen of twenty do.
4. Extending the horizon from 2e6 to 1e7 does not remove the separation: at
   `0.80` and `0.90` the FIFO mean backlog keeps rising to 1.9e6 and 3.0e6
   while NTO stays flat, and at `0.70` both policies remain bounded over the
   whole 1e7 slots.

No rate is declared best here, and no asymptotic claim is made: the slopes and
backlogs above are finite-horizon measurements on this instance.

## Reproducibility metadata

| item | value |
|---|---|
| python | 3.10.20 |
| machine | pcni-Super-Server, 128 cores |
| workers | 60 |
| runs | A 320, B 60 |
| sampled points | A 320,320, B 60,060 |
| wall-clock | 7 minutes total |
| lambda* | 0.980392 (unchanged loads: u1 = 1.00, v1 = 1.02) |
