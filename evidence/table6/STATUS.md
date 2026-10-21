# Table 6 DynVMP campaign status

Last checked against the remote scheduler: server-local 2026-10-20 12:31:51.

- Protocol: 150 jobs, 100,000 slots, seeds 1/2/3, real `dynvmp_bridge`.
- Completed successfully: 150.
- Running: 0.
- Queued: 0.
- Failed: 0.
- Scheduler, simulation workers, and DynVMP bridge subprocesses: not observed;
  sampled job logs did not advance during this check.
- Latest scheduler event: server-local 2026-10-17 13:25:08.
- Latest sampled job-log activity: server-local 2026-10-17 13:25:07.
- CSV files currently present in the remote result root: 301.
- Error-pattern scan: no matching log files.
- Remote result root: `results_k_runtime_100000_seed123_20260927`.

All 150 per-run CSVs are archived under `evidence/table6/raw`. The generated summary is `evidence/table6/summary/paper_table_k_runtime_across_rates.csv`. Invocation counts and times match the corrected LaTeX source at its printed precision. See `evidence/table6/paper_update/`; the older PDF timing mismatch is historical. No updated compiled PDF was verified.
