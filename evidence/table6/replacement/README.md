# Table 6 manuscript handoff

These files replace the ten timing entries using all 150 verified 100k-slot
run rows in `evidence/table6/raw/`, averaged over three seeds and five rates
per topology/frame. Their immediate source is
`evidence/table6/summary/paper_table_k_runtime_across_rates.csv`.

- `table6_rows.tex`: replace only the existing five data rows; preserve the
  paper's caption, label, column definitions, and surrounding environment.
- `table6_text.tex`: replacement reduction sentence and measurement caveat.
- `table6.csv`: full-precision rerun values, printed replacements, and current
  PDF timing values side by side.
- `reductions.json`: reductions computed before rounding (98.8% and 98.1%
  for mapping time, at one decimal place).
- `CORRECTION.md`: generated old/new timing comparison for manuscript review;
  this is not authorization to publish before the paper is updated.

Thresholds and invocation counts do not change. Timing is complete mapping-call
wall time on the recorded loaded host, not isolated solver CPU time.

```bash
python scripts/generate_table6_replacement.py --check
python scripts/generate_table6_replacement.py
```

The numeric rows and reduction sentence are now verified in the supplied
corrected project; see `../paper_update/`. The optional additional method
paragraph was not added to the manuscript, as requested by the owner.
The comparison with the old PDF is retained for historical provenance.
No new compiled PDF is claimed. A later PDF binding requires checking the
actual compiled values, not merely updating a filename or hash.
