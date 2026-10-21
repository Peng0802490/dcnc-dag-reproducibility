# New Section 7.2 Simulation - Correction and Audit Log

Date: 2026-07-23

## Scope

This log records two issues found during the second, source-level review of the
new Section 7.2 simulation. The canonical deliverables use the corrected
measurement and deterministic execution conditions described below. No result
from the superseded first pass is used as a paper-facing value.

## 1. Physical backlog metric

### Finding

The simulator method `PhysicalNetwork.total_backlog()` returns

1. the number of synchronization-pool entries,
2. the number of link-queue objects, and
3. the number of node-queue objects.

It is therefore an object count, not a workload quantity. Labeling its
second-half slope as `workload units/slot` was incorrect.

### Correction

The canonical driver passively records remaining link and node workload from
`size_remaining`. It also adds the payload sizes of inputs that have reached a
synchronization pool but have not yet released the downstream function. The
paper-facing physical metric is consequently

```
sum(link item size_remaining)
+ sum(node task size_remaining)
+ sum(payload size already held in synchronization pools).
```

The original object count is retained under an explicit
`physical_object_backlog` name as a sensitivity diagnostic. Instrumentation is
called through the simulator's existing statistics hook and does not change
queue selection, service, arrivals, wireless states, or mapping decisions.

Because full queue scans become quadratic in the overloaded fixed-mapping
case, the canonical driver maintains exact totals in integer `0.1`-workload
units at enqueue, service, and synchronization events. It checks the final
incremental state against a complete object scan. A separate 64-row validation
finds bit-exact behavior, object slopes, and virtual slopes; the maximum
physical-workload slope difference is `4.8073e-14`, below `1e-12` and explained
by floating-point summation order.

### Effect on the conclusion

With the fixed cutoff `slope > 0.05`, the corrected physical-or-virtual
workload diagnostic is first positive for all five seeds at offered rate
`1.05`, or 5% beyond `lambda*=1`. The object-count sensitivity diagnostic is
first positive for all five seeds at `1.03`, but that 3% value is not a
workload-based resolution result and must not be quoted as such.

## 2. Equal-weight matching reproducibility

### Finding

The simulator uses NetworkX maximum-weight matching for primary-interference
activation. Equal-weight alternatives can depend on iteration order, which in
turn can change across Python interpreter launches when `PYTHONHASHSEED` is not
fixed.

In a 35-run rerun of the superseded first pass, arrival paths, arrival totals,
and mapping-call counts matched exactly, but 8 of 35 completed-request counts
differed by 1 to 4 requests. Fourteen request-level mapping shares differed,
with maximum absolute difference `2.2462273590495574e-4`. These differences do
not change the qualitative capacity conclusion, but they violate exact-run
reproducibility.

### Correction

The canonical driver refuses to start unless `PYTHONHASHSEED=0`. Formal and
second-pass commands both set it explicitly. The corrected campaign records
arrival and wireless sample-path SHA-256 values, checks paired main/ablation
paths, and is independently rerun for exact row-level comparison.

## 3. Canonical status

The final report and packaged `results/canonical` directory are the only
paper-facing outputs. Their audit reports verify the run grid, arithmetic,
aggregation, flags, sample-path pairing, LP decomposition, and deterministic
second-pass reproduction. The superseded raw pass remains outside the delivery
package to avoid accidental use.
