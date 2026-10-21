# Latest-paper MoE figure evidence

This is the 100,000-slot campaign used by Fig. 4(a,b) of the user-designated
2026-10-16 paper. It is separate from the 50,000-slot Table 5 campaign under
`evidence/moe/`; do not use this plotting grid to redefine Table 5 thresholds.

The import contains all 321 run JSON records, their merged CSV, 321 compressed
unfinished-arrival files (179,264 requests), the protocol and runtime
compatibility record, 107 three-seed aggregates, and the two archived paper
figure PDFs. Imported files are byte-preserved and listed in
`import_manifest.json`. Historical relative paths inside original records
describe the execution workspace; the verifier resolves their release copies
explicitly rather than rewriting those records.

The plotted metric is `(completed_delay_sum + sum(T - arrival_slot for
unfinished requests)) / total_arrivals`, averaged equally over seeds 0/1/2.
It is a finite-horizon all-request delay lower bound, not completed-only delay
and not a fixed unfinished-request penalty. The paper's wording review was
explicitly deferred; this package records the actual computation without
editing the manuscript.

The paper displays 106 points: all 107 aggregates except Llama/DCNC-DAG-H at
arrival rate 1.05. That point and all three underlying runs remain archived.
`figures/plot_audit.json` records the display-only omission. The archived
paper PDFs retain their original axis text. The portable redraw labels the
actual metric and reproduces the numeric points, not byte-identical fonts.

From the artifact root:

```bash
python scripts/verify_moe_censored.py
python scripts/reproduce_moe_censored.py
PYTHONHASHSEED=0 python scripts/run_moe_censored_delay.py \
  --output results/moe_censored_rerun --seeds 0 1 2 \
  --horizon 100000 --memoize-routing --workers 4 --no-plot
```

The last command reruns the complete 321-job campaign and can take substantial
time. It refuses to write outside `results/`. `source/` preserves the original
measurement and plotting scripts as provenance; the runnable release entry
point changes repository paths and defaults, not simulator logic. The exact
simulator hashes in `protocol.json` are verified against the included code.
