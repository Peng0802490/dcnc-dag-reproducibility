# DCNC-DAG: code and data

Code and experiment data for *Throughput-Optimal Control of Distributed
Computing Networks for Service DAGs*.

Version **0.1.1**.

## Install

Use Python 3.11. Create and activate a virtual environment, then run from
this directory:

```bash
python -m pip install -r requirements.txt -c constraints-main.txt
python -m pip install -e . --no-deps
```

## Reproduce figures and tables

```bash
python scripts/reproduce_paper_results.py
```

This reproduces the figures and tables from the supplied data without running
simulations. Output is written to `results/exports/`, `results/tables/` and
`results/figures/`.

### Delay metric

For each simulation run of \(T\) slots, we sum the completion delays of finished requests and the elapsed ages of unfinished requests, then divide by the total number of arrivals. A request is completed only when all its sink outputs have been delivered. This gives a finite-horizon lower bound on the average request delay, since the remaining delays of unfinished requests are not counted.

When the arrival rate lies strictly within the capacity region and the policy stabilizes the network, the uncounted delay per arrival becomes negligible as \(T\to\infty\), provided the mean request delay is finite. Thus, the lower bound approaches the actual mean request delay.
