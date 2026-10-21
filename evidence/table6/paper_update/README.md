# Corrected Table 6 source evidence

The current paper source is `DCNC_DAG_Table6_timing_updated_project.zip`,
SHA-256 `7e3e4d8f240ae000656c3de4371ec3d43bfaaf703416439afcfb234a820f2fb4`.
The full manuscript project is not redistributed here. `source_audit.json`
records the exact ZIP identity, all 18 project member hashes before and after
the correction, changed source line numbers, and hashes of three excerpts.

Only the five timing rows and the reduction sentence in `TMC_Main.tex`, plus
the sample-count explanation in `TMC_Appendices.tex`, changed. The remaining
16 project members, including every figure and the bibliography, are identical
to the preceding supplied project.

`table6.tex`, `reductions.tex`, and `appendix_overhead.tex` are byte-exact
source excerpts. Verification recomputes their numerical values from all 150
raw runs, checks displayed precision and the unchanged supported rates/calls,
and checks all four reduction percentages. With the external project present,
it additionally checks its ZIP hash, every member, and excerpt byte ranges:

```bash
python scripts/verify_paper_update.py
python scripts/verify_paper_update.py --project ../DCNC_DAG_Table6_timing_updated_project.zip
```

This is source verification only. No updated compiled PDF was supplied or
checked, and no LaTeX compilation is claimed. The older PDF and its audit are
historical. The owner requested release preparation without adding manuscript
method prose. Existing artifact documentation still explains that these are
loaded-host complete mapping-call wall times, not isolated solver CPU times.
