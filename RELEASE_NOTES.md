# DCNC-DAG reproducibility artifact v0.1.0

MIT-licensed source and data artifact, aligned with the corrected LaTeX
project. Formal archives pass strict verification before delivery.

This artifact accompanies *Throughput-Optimal Control of Distributed Computing
Networks for Service DAGs*. It includes the simulator, fixed experiment
inputs, paper-relevant per-run data, aggregation and plotting scripts,
environment definitions, third-party notices, and integrity checks.

## Data coverage

- LP capacity, driving and random-DAG comparisons, workflow experiments,
  frame-length results, and FIFO/NTO evidence.
- MoE Table 5: all 504 runs from the 50,000-slot campaign.
- MoE Fig. 4(a,b): all 321 runs from the separate 100,000-slot campaign,
  including unfinished-request records and the display-omitted endpoint.
- Table 6: all 150 successful runs, original server hashes, summaries, and
  machine-generated replacement rows and reduction percentages.

## Paper alignment and scope

Table 6 in `DCNC_DAG_Table6_timing_updated_project.zip` matches the 150-run
evidence, including all ten times and the 98.8% / 98.1% time reductions.
Supported rates and call counts are unchanged. Pinned source excerpts and
project hashes are in `evidence/table6/paper_update/`. The older PDF discrepancy
is historical, not a discrepancy with the corrected source project.

No updated compiled paper PDF was supplied or verified. The manuscript method
prose is left unchanged at the owner's request; its numerical update is not
represented as a new timing experiment or an isolated solver benchmark.

Timing is complete mapping-call wall time on a loaded host, not isolated
solver CPU time. MoE table and figure campaigns have different horizons;
the figure metric includes unfinished-request ages. See
[`REPRODUCIBILITY_STATUS.md`](REPRODUCIBILITY_STATUS.md) for scope.

## Reproduce and verify

```bash
python scripts/verify_claims.py --strict
python scripts/maintain_artifact.py verify --strict
```

See [`README.md`](README.md) for installation, smoke runs, and reproduction.
Numerical evidence can be checked without the original campaign server or a
Gurobi license. Rerunning the original DynVMP experiments requires the
documented legacy environment and the user's own licensed Gurobi installation.
Gurobi, credentials, and the paper PDF are not included.

First-party material is MIT-licensed; third-party material retains the rights
and attribution requirements in `THIRD_PARTY.md`. Citation metadata is in
`CITATION.cff`. The accompanying archive JSON records actual local verification
results, source identity, and archive hash. Local checks do not imply that
hosted GitHub Actions has already run.
