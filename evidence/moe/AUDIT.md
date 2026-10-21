# MoE evidence audit: latest designated paper

Audit date: 2026-10-20. Current PDF identity is recorded in `audit.json`.
Table 5 on page 10 now agrees with the canonical Milan-v2 raw campaign:

| Model | DCNC-DAG-H | Lazarus-inspired | FlexMoE-inspired | Gain |
|---|---:|---:|---:|---:|
| Mixtral | 1.16 | 0.35 | 0.46 | 2.52x |
| Llama | 1.02 | 0.28 | 0.38 | 2.68x |

The verifier checks all 504 raw rows, the 0.95 mean completion gate, three
seeds, and the 50,000-slot horizon. The earlier 0.52/0.44 mismatch refers
to the September PDF, not the current manuscript. Its unchanged audit,
lineage, hashes, and alternative-convention checks are under `history/`.

Fig. 4(a,b) uses the separate 100,000-slot campaign in
`evidence/moe_censored/`. All 106 displayed points match the raw
all-request delay lower bounds. All 107 aggregates and 321 runs are included;
Llama/DCNC-DAG-H at 1.05 is a documented display-only omission.
The two horizons must not be conflated. The user deferred manuscript wording
changes; the artifact records actual metrics without modifying the paper.

The legacy config's hop-count routing description is stale; the executed
Milan-v2 runner and current paper use queue-aware routes. Original config
bytes are preserved as provenance, not silently repaired.
