# DCNC-DAG: code and data

Code and experiment data for *Throughput-Optimal Control of Distributed
Computing Networks for Service DAGs*.

## Contents

| Directory | Contents |
| --- | --- |
| `src/dcnc_sim/` | Network/DAG models, mapping algorithms, physical/virtual queues and scheduling |
| `scripts/` | Experiment runners, aggregation and plotting; FIFO/NTO code is in `scripts/fifo/` |
| `tools/` | Policy/frame sweeps and the optional DynVMP bridge |
| `inputs/` | Configurations, DAGs, topologies, full experiment matrix and plot settings |
| `data/runs/` | Results from 3,628 server runs, FIFO trajectories and unfinished MoE request arrivals |
| `data/table6.csv` | The 150 timing measurements used for Table 6 |
| `third_party/` | Required DynVMP dependency modules and their licenses |

## Install

Use Python 3.10 or newer. From this directory:

```bash
python -m pip install -r requirements.txt -c constraints-main.txt
python -m pip install -e . --no-deps
```

## Reproduce figures and tables

```bash
python scripts/reproduce_paper_results.py
```

This aggregates the supplied data without running simulations. Output is
written to `results/exports/`, `results/tables/` and `results/figures/`.
Use `--output PATH` to change the destination, or `--skip-figures` for numbers
only. PDF/PNG figures and derived tables are generated on demand.

Request completion requires all sink outputs. Main-policy, frame and workflow
delays use `stats.avg_service_delay_completed`; supported rates use a mean
`completed_service_units / total_service_units` of at least 95%. MoE delay
plots use completed-request delays plus unfinished-request ages, divided by
arrivals. Values are averaged over seeds. Frame/workflow bands are one standard
error; FIFO/NTO bands are 95% confidence intervals.

The 13 PDF filenames match the manuscript, and frame length is written **F**.
The plot settings retain the chosen display ranges, including omission of the
FlockLab DCNC-DAG-H point at arrival rate 3.12. All simulated rates remain in
the data. Fonts use Times New Roman when available, otherwise DejaVu Serif.

## Run simulations on a server

```bash
python scripts/run_campaign.py --workers 96
```

Run on a Linux server; adjust `--workers` to its resources. The full matrix is
`inputs/experiments.json`. New runs go to `results/campaign/`, or to the directory
specified by `DCNC_CAMPAIGN`. Completed runs can be resumed. The simulator uses
nonpreemptive service, next-slot successor eligibility, lexicographic virtual
max-weight activation and CTS placement based on placed direct predecessors.

The optional `dynvmp_bridge` solver uses Python 2.7 and separately licensed
Gurobi. Its environment is specified in `environment_dynvmp_py2.yml`; set
`DYNVMP_PYTHON` and `GRB_LICENSE_FILE` before using `tools/run_dynvmp_bridge.sh`.
The standard `exact_dp` solver and figure/table reproduction do not need it.

## License and data attribution

First-party code and material are covered by [MIT](LICENSE), subject to the
third-party terms below. Original third-party license files are retained.

- [alib](https://github.com/vnep-approx/alib) and
  [vnep-approx](https://github.com/vnep-approx/vnep-approx): MIT; see
  `third_party/alib/LICENSE` and `third_party/vnep_approx/LICENSE`.
- [Internet Topology Zoo](https://topology-zoo.org/), by Simon Knight,
  Hung X. Nguyen, Nickolas Falkner, Rhys Bowden and Matthew Roughan:
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Its original
  attribution is retained at `third_party/alib/LICENSE.topology`.
- FlockLab adaptations use *Wireless Link Quality Estimation on FlockLab -
  and Beyond*, v1.0.0, by Romain Jacob, Reto Da Forno, Roman Trüb, Andreas
  Biri and Lothar Thiele, [DOI: 10.5281/zenodo.3354718](https://doi.org/10.5281/zenodo.3354718),
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Adaptations retain
  directed links with positive mean reception, derive `p_on`, add normalized
  capacities and apply the `cap210` / `access` transformations.
- `workflow_srasearch22.json` adapts the public dependency structure of
  `srasearch-chameleon-10a-004.json` from
  [wfcommons/WfInstances](https://github.com/wfcommons/WfInstances), LGPL-3.0,
  into the simulator's service-function schema and normalized factors.
- `workflow_sipht31.json` reconstructs the public task/dependency structure
  of [Pegasus SIPHT Run 1](https://pegasus.isi.edu/workflow_gallery/gallery/sipht/index.php)
  with first-party normalized factors. Pegasus is Apache-2.0 licensed; its
  gallery does not separately label this archived run. No original WfInstances
  JSON or Pegasus archive is redistributed.

Python dependencies remain under their respective upstream licenses.
