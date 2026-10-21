# Reproducibility status

Status date: 2026-10-21. Artifact version: `0.1.0`.
The current authority is `DCNC_DAG_Table6_timing_updated_project.zip`, SHA-256
`7e3e4d8f240ae000656c3de4371ec3d43bfaaf703416439afcfb234a820f2fb4`.
The corrected Table 6 is verified in LaTeX source, not in a newly compiled PDF.
The earlier 2026-10-16 PDF remains the historical baseline for unchanged
results; its original hash and timing discrepancy are preserved.

| Paper result | Status | Included evidence |
|---|---|---|
| LP capacity boundary | Exact | `evidence/lp_capacity/` |
| Driving and random-DAG supported rates | Exact at reported precision | `evidence/main_sweeps/` |
| Workflow supported rates | Exact | `evidence/workflow/` |
| Frame-length supported rates | Exact at reported precision | 480 records in `evidence/main_sweeps/k100k.jsonl` |
| FIFO/NTO backlog | Exact numeric redraw | `evidence/fifo/` |
| Table 5 MoE rates and gains | Exact; old mismatch resolved | 504 runs in `evidence/moe/raw/`, horizon 50,000 |
| Fig. 4(a,b) MoE curves | Exact numeric data | 321 runs, 107 aggregates and 106 displayed points in `evidence/moe_censored/`, horizon 100,000 |
| Table 6 invocation counts | Exact at reported precision | 150 original CSVs in `evidence/table6/raw/` |
| Table 6 absolute timing and reductions | Exact at corrected source precision | 150 runs and `evidence/table6/paper_update/` |

## Scope

The current MoE table reports 0.46/0.38 and gains 2.52/2.68, matching the
50k raw data. The September discrepancy is historical, retained under
`evidence/moe/history/`. Fig. 4 uses a separate 100k all-request delay lower
bound including unfinished-request ages. All records and the display-omitted
Llama endpoint are retained. The user deferred manuscript metric/horizon
wording changes; this artifact documents the actual formula without editing
the paper.

FlockLab's common 0.95 completion gate gives 3.432 (table: 3.43), while its
stricter figure display trim ends at 3.12. Both conventions are retained.

Table 6 timing covers the complete mapping call, including bridge overhead
and contention from up to 75 processes on a 64-core host. The new campaign
does not validate the older PDF timings. The updated project contains the
corrected times and reductions. The source audit verifies that only those
numbers and the appendix sample-count explanation changed; the other 16
project members are byte-identical to the preceding supplied project.

## Release status

The owner selected MIT on 2026-10-21. `LICENSE` and project metadata record
that selection; third-party material retains its own licenses and notices.

After supplying the corrected source project, the owner requested release
preparation without adding further manuscript method prose. The first-party
license and numerical source-alignment gates are closed. This does not claim
that a new paper PDF was compiled or checked. No manuscript edits are made by
this release preparation, and existing timing caveats remain in the artifact.

Formal archives require all strict checks to pass. Earlier candidate archives
remain historical and must not be renamed or uploaded as this release.
All pre-existing paper and release changes are preserved; snapshot packaging
does not commit or push and excludes Git internals, credentials, and runtimes.
