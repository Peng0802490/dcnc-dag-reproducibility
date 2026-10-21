# Table 6 data correction

Historical comparison: these corrected numbers are now verified in the
updated LaTeX project. The old PDF remains a historical baseline; no
updated compiled PDF was supplied or verified. See `../paper_update/`.

Bound PDF SHA-256: `B093E7ABE5138E9AD71548BF70E1FC0E54B7D8681A664337369B474B30FCD006`.

Source: all 150 verified runs in `evidence/table6/raw/`, aggregated in
`evidence/table6/summary/paper_table_k_runtime_across_rates.csv`. Each topology/frame row averages
three seeds and five arrival rates, with 100,000 slots per run.

| Topology | Frame length | Bound PDF seconds/slot | Verified replacement seconds/slot |
|---|---:|---:|---:|
| Milan | 1 | 1.91 | 2.825 |
| Random | 1 | 11.33 | 11.028 |
| Milan | 4 | 1.13 | 1.626 |
| Random | 4 | 7.77 | 7.254 |
| Milan | 16 | 0.391 | 0.528 |
| Random | 16 | 3.32 | 2.991 |
| Milan | 64 | 0.104 | 0.139 |
| Random | 64 | 0.942 | 0.852 |
| Milan | 256 | 0.0261 | 0.0349 |
| Random | 256 | 0.23 | 0.209 |

Supported rates and invocation counts are unchanged at paper precision.
Using full-precision values before rounding, mapping time decreases by
98.8% on Milan and 98.1% on Random from frame length 1 to 256.

These are complete mapping-call wall times, including bridge I/O, process
startup, solving, parsing, and contention from up to 75 experiment
processes on a 64-core host. They are not isolated solver CPU times.

The numeric rows and reductions have been applied in the supplied project.
The additional method paragraph in `table6_text.tex` is a suggested
handoff only: the owner declined adding it to the manuscript. The
full-precision historical comparison remains in `table6.csv`.
