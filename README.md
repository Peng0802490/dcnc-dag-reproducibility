# DCNC-DAG reproducibility artifact

This directory is the maintained open-source reproducibility artifact for the
DCNC-DAG paper. It contains the simulator, experiment entry points, fixed
inputs, paper-facing evidence, third-party DynVMP snapshots, and machine-readable
release gates.

The delivery binds `DCNC_DAG_Table6_timing_updated_project.zip`, the
user-designated corrected LaTeX project. Table 6 matches all 150 successful
runs at the displayed precision, including the 98.8% and 98.1% time reductions.
Table 5 MoE thresholds match the 50k raw data; MoE figures are backed by the
separate 100k campaign. See `evidence/table6/paper_update/` for source evidence.

First-party material is licensed under [MIT](LICENSE); third-party rights
remain as documented in [THIRD_PARTY.md](THIRD_PARTY.md). The owner approved
release preparation without expanding the manuscript's method prose. The
artifact retains its measured timing scope and host-load documentation.
Verification is against source: no updated compiled PDF has been verified.
The older PDF and timing audit are retained explicitly as historical evidence.
See `REPRODUCIBILITY_STATUS.md`, `evidence/moe_censored/README.md`, and
`evidence/table6/replacement/README.md`.

For the repository layout, upload procedure, and release attachments, see
[`docs/GITHUB_RELEASE.md`](docs/GITHUB_RELEASE.md). The prepared release
description is [`RELEASE_NOTES.md`](RELEASE_NOTES.md). Publish only the
extracted artifact, never the parent paper workspace.
中文详细教程：[`docs/GITHUB_RELEASE_ZH.md`](docs/GITHUB_RELEASE_ZH.md)。

## Fast verification

The evidence checks use only the Python standard library:

```bash
python scripts/verify_claims.py
python scripts/maintain_artifact.py verify
```

The first command recomputes paper-facing thresholds from the included raw
records. The second verifies every maintained file against `SHA256SUMS.txt`,
scans the current first-party material for machine-specific paths or obvious
credentials, and repeats the same publication-safety checks over every blob
reachable from Git history. It also rejects common secret-bearing filenames
such as `.env`, private-key containers, `gurobi.lic`, and credential JSON/YAML
files in either the current artifact or a deleted/renamed historical path. The
same command verifies the pinned third-party license files, dataset notices,
adapted-data hashes, source metadata, and vendored Topology Zoo file counts. It
also requires the generic requirements, project dependencies, exact Conda
environments, pip constraints, and captured runtime fingerprint to remain
mutually consistent. `SBOM.spdx.json` is regenerated conceptually from those
authoritative dependency and third-party inputs, and verification fails if the
committed SPDX 2.3 document drifts from them.

The repository includes `.github/workflows/artifact-integrity.yml`. On pushes,
pull requests, and manual dispatches it checks out complete Git history, uses
the captured Python version and `constraints-main.txt`, repeats the integrity,
claim, unit-test, Python, and shell checks, then clean-room builds a candidate
archive. Version-tag pushes additionally require strict checks and a formal
archive. The workflow has read-only repository permissions, does not use
secrets, and never publishes automatically.

Inside the maintained paper workspace, additionally bind the evidence to the
user-designated corrected source project:

```bash
python scripts/verify_claims.py --strict --paper-project "../DCNC_DAG_Table6_timing_updated_project.zip"
```

This fails if the ZIP has changed without a corresponding evidence and claims
update. The archive builder performs this check automatically whenever that
parent-workspace ZIP is present and records the result in the archive metadata.
The full project is not redistributed: the archive includes only the numeric
source excerpts and their provenance. `--paper` still checks the historical
PDF identity; it does not validate the corrected source or a new compiled PDF.

Use the strict gate immediately before a public release:

```bash
python scripts/verify_claims.py --strict
python scripts/maintain_artifact.py verify --strict
```

Strict verification intentionally fails while any blocker in
`manifests/claims.json` remains open. The license gate requires both a
substantive top-level `LICENSE` and non-empty `[project].license` metadata in
`pyproject.toml`.

## Install the Python 3 simulator

```bash
conda env create -f environment_dcnc_dag.yml
conda activate dcnc_dag
python -m pip install -e .
python scripts/run_edge_experiments.py --help
```

For a small non-DynVMP smoke test:

```bash
python scripts/run_edge_experiments.py \
  --output-dir results/smoke \
  --slots 100 --seeds 1 --seed-start 1 \
  --cases driving_milan --policies DCNC-DAG \
  --interference-model primary --fixed-k 1 --dcnc-solver exact_dp
```

## Rebuild the paper-facing plot data

```bash
python scripts/reproduce_paper_results.py
```

This rebuilds the policy-comparison and frame-length CSVs under
`results/plots/`, checks the Workflow and MoE summaries, and regenerates the
FIFO/NTO figures when the plotting dependencies are installed. It never edits
the immutable evidence under `evidence/`; FIFO/NTO data and plotting code are
copied into an isolated `results/fifo/` workspace before rendering.

## Exact DynVMP path

The Python 3 simulator can invoke the original Python 2 DynVMP implementation
through `tools/dynvmp_bridge.py`. The exact source snapshots used by the
current server are included under `third_party/alib/` and
`third_party/vnep_approx/`, with their MIT license files preserved.

DynVMP additionally requires Python 2.7 and a separately licensed Gurobi
installation. Create the legacy environment with
`environment_dynvmp_py2.yml`, then set `DYNVMP_PYTHON` and `GRB_LICENSE_FILE`
if their defaults do not match the local installation. Gurobi and its license
are not redistributed in this artifact.

The exact wrapper executed by the completed Table 6 server campaign is archived
under `evidence/table6/runtime/`. The public wrapper differs only in locating
the vendored dependencies and generated runtime directory. Host, interpreter,
Gurobi, source-hash, and third-party tree-comparison evidence is recorded in
`evidence/table6/runtime_fingerprint.json`.

The Table 6 timer covers the complete `solver.compute(...)` call, including
bridge serialization, process startup, result parsing, and concurrent host
contention. The campaign used up to 75 panes on a 64-core host. Its output is
therefore a documented loaded-host measurement, not an isolated solver-latency
benchmark. All 150 successful raw result CSVs, server hashes, and generated
summaries are included. `evidence/table6/IMPORT_20261020.md` records the import,
reproduction commands, and historical paper comparison. The current source
comparison is in `evidence/table6/paper_update/`; its timing gate is closed.

## Layout

- `.github/workflows/`: read-only continuous integrity verification.
- `src/dcnc_sim/`: simulator implementation.
- `scripts/`: experiment, aggregation, verification, and maintenance entry points.
- `tools/`: exact mapping bridge and paper-data builders.
- `legacy_inputs/`: network, DAG, and experiment configurations.
- `evidence/`: immutable raw/aggregated records used for paper claims.
- `third_party/`: exact DynVMP dependency snapshots with retained licenses and
  dataset attribution; see `THIRD_PARTY.md` and `manifests/third_party.json`.
- `manifests/`: claim status, provenance, and generated file inventory.
- `CITATION.cff`: artifact citation plus the title and author order of the
  byte-pinned paper PDF.
- `SBOM.spdx.json`: deterministic SPDX 2.3 inventory for pinned Python,
  vendored-code, and data-source components.
- `docs/`: environment and release-maintenance documentation.

Imported numeric evidence is unchanged. A few historical provenance strings
containing a server home directory are replaced with `${ARTIFACT_ROOT}` for
safe publication. The LP subdelivery keeps its original manifest as
`SHA256SUMS.source.txt`; `SHA256SUMS.txt` verifies the normalized release copy.

## Maintenance rule

Before importing a revised paper or experiment, detect drift in the pinned project
and the already-local parent Git refs:

```bash
python scripts/check_upstream_state.py --require-inputs --fail-on-change
```

This command is read-only and does not access the network. Maintainers should
run `git fetch origin` in the parent paper repository first when they want the
cached `origin/master` comparison to reflect the server. A reported change is
a prompt to review and synchronize the package, not permission to overwrite
evidence automatically.

After importing a new experiment result, update its evidence directory and
`manifests/claims.json`, run the two non-strict checks, then refresh hashes:

```bash
python scripts/maintain_artifact.py sanitize-imported-provenance
python scripts/generate_sbom.py
python scripts/maintain_artifact.py refresh
python scripts/verify_claims.py --paper-project "../DCNC_DAG_Table6_timing_updated_project.zip"
python scripts/maintain_artifact.py verify
```

When assigning a new artifact version, keep the `[project].version`, claims
manifest, newest changelog section, and validation record synchronized. The
standard verifier rejects any disagreement; regenerating the SBOM then carries
the same version into its package identity.

Do not mark `release_ready` true until every strict gate passes.

For an in-progress Table 6 poll, update both the machine-readable record and
its rendered status with `scripts/update_table6_progress.py`; do not edit the
two files independently. The updater rejects stale timestamps, decreasing
completion/CSV counts, inconsistent totals, and changes to the campaign root.
Generate the input from scheduler structure rather than parsing its display
log. Run the read-only probe on the campaign host and pipe its JSON to the
maintained checkout, for example:

```bash
ssh <campaign-host> \
  'cd <artifact-checkout> && python scripts/table6_progress_probe.py \
    --result-root <campaign-result-root> --expected-jobs 150 \
    --scheduler-pid <scheduler-pid> --sample-seconds 5' \
  | python scripts/update_table6_progress.py --snapshot-json -
```

The probe derives completed and failed counts from `done/*.exit`, dispatched
jobs from `scripts/*.sh`, and queued jobs from the declared total. It also
requires a one-to-one dispatched-job/log mapping, checks PID liveness, samples
log growth, counts result CSVs, and scans job logs for fatal/error patterns.
Neither command stores an SSH target, credential, or token.

The Table 6 campaign finished on 2026-10-17 and all 150 result CSVs were
imported on 2026-10-20. `verify_claims.py` now checks their server hashes,
command/result correspondence, and recomputed means and reductions. To rebuild
the summaries without modifying evidence:

```bash
python scripts/summarize_k_runtime_across_rates.py \
  --input-root evidence/table6/raw \
  --output-dir results/table6_summary \
  --commands-csv evidence/table6/commands.csv
```

For a future campaign, download its compact result files outside the artifact
and validate a staged import into a new destination:

```bash
python scripts/import_table6_results.py \
  --input-root results_k_runtime_100000_seed123_20260927 \
  --output-root results/table6_import_candidate
```

The importer requires every command/result tuple to match and refuses partial
or overwriting imports. After reviewing a future candidate, use a new evidence
directory, generate summaries with `scripts/summarize_k_runtime_across_rates.py`,
and update the claim references. Preserve the current `evidence/table6/raw`
snapshot. Do not close the Table 6 gate merely because all jobs finished:
the generated aggregates must reproduce the paper or the paper must be
reconciled with the new evidence.

## Build a delivery archive

The formal archive command refuses to run unless the worktree is clean and all
strict release gates pass:

```bash
python scripts/build_release_archive.py
```

Before publishing the ZIP, the builder creates the Git source archive twice,
requires byte-identical digests, verifies every manifested member, extracts the
archive into a temporary clean directory, and reruns the claim checks,
integrity scan, unit-test suite, and Python compilation from that extracted
copy. Archive validation rejects duplicate or case-colliding members, symbolic
links, path traversal, and filenames that cannot be represented safely on
Windows. It also rejects interpreter caches, test/tool caches, coverage files,
and generated `*.egg-info` metadata even if they were accidentally committed.
It then builds a wheel from the extracted copy with the pinned
setuptools backend and no network or build isolation, installs that wheel into
a separate target directory, and imports `dcnc_sim` from the installed
location. The adjacent JSON metadata records the actual Python, packaging-tool,
and operating-system identity used for those checks. A failure at any stage
prevents the delivery files from being published.

During maintenance, an explicitly marked internal candidate can be built with
`python scripts/build_release_archive.py --candidate`. Candidate archives are
never substitutes for the formal archive: their filename and metadata record
the commit and the fact that strict release gates were not required.

## Build an uncommitted, verified delivery

```bash
python scripts/verify_moe_censored.py
python scripts/generate_table6_replacement.py --check
python scripts/build_release_archive.py --worktree-snapshot
```

The snapshot mode packages exactly the verified file manifest, including
uncommitted imports, without staging or committing. Its metadata separates
the base Git revision from the snapshot identity. Two independent ZIP builds
must be byte-identical; extracted verification, tests, wheel build/install,
and import must pass. Strict checks are mandatory for this formal archive.

Deliver the ZIP and its adjacent `.sha256` and `.json` metadata. Do not
upload runtimes, working results, or the parent paper repository. The external
paper project and historical PDF are identified by hash, not implicitly
redistributed. Only the relevant Table 6 source excerpts are included.
