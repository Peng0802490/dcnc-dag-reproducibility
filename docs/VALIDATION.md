# Validation record

## Input-layout maintenance - 2026-10-21

Validation target: artifact version `0.1.1`. This release preserves all
v0.1.0 numerical evidence and reorganizes inputs only. CPython 3.10.20 passed:

- All 42 tests, including eight input-layout/provenance regressions.
- All 104 input migration records, 56 configurations and their references,
  and byte identity of all 995 evidence files relative to v0.1.0.
- Identical 100-slot workflow outputs using new and supported old paths,
  plus a 100-slot Milan/Mixtral DCNC-DAG-H smoke run.
- Eight random5/random6 configuration checks and all four topology/config
  generators in an isolated temporary copy, without changing maintained inputs.
- Strict claims, the explicitly supplied updated paper-project binding,
  all 2047 maintained hashes, Git-history safety, SBOM/third-party checks,
  source compilation, and `pip check`.
- A formal prepublication snapshot: identical repeated archive builds,
  clean-extraction strict checks and tests, and wheel build/install/import.

The final committed archive and hosted tag run are checked separately before
publication; its adjacent `.zip.json` records the completed build identity.
The v0.1.0 ZIP retains SHA-256
`b7d06f19dd02a61519798d90d1ad30100a69f746218504fbfd8981b0093da467`.
The existing v0.1.0 release and manuscript reference remain unchanged.

Known pre-existing limitation: the auxiliary `run_project_case.py` runner
imports an unavailable `StaticMinCostSolver`, also present in v0.1.0. It is
not runtime-validated here; this directory-only change does not modify the
mapping algorithms. Workflow and MoE entry points passed the checks above.

## Formal release preparation - 2026-10-21

Validation target: artifact version `0.1.0`. The corrected source ZIP is bound
by SHA-256 and its Table 6 excerpts independently match all 150 raw runs,
displayed timings, supported rates, call counts, and derived percentages.
The strict claim and integrity gates pass with no open publication gates.
The previous PDF discrepancy remains historical; no updated compiled PDF or
LaTeX compilation is claimed. The owner declined further manuscript method
prose and requested release preparation, not an automatic upload.

The CPython 3.10.20 environment passed all 34 tests, all 2043 maintained file
hashes, current-tree and Git-history safety checks, the SBOM/environment and
third-party checks, source compilation, `pip check`, CSV reproduction, and
the source-project/upstream-state check. Regressions reject altered paper
excerpts, old timing values declared exact, and an incorrect external ZIP.

Formal delivery additionally requires two identical snapshot builds, strict
extracted claim/integrity checks, the test suite, and wheel build, selected
license inclusion, installation, and import. The adjacent `.zip.json` records
the actual completed build and archive hash. GitHub-hosted CI remains to be
run after the owner creates and pushes the public repository.

## GitHub preparation - 2026-10-21

Validation target: artifact version `0.1.0`, using CPython 3.10.20 and the
captured dependency environment. The owner selected MIT and requested that
final publication wait for the updated Table 6 paper.

The preparation passed all 31 artifact tests, current-file and Git-history
safety checks, the deterministic SBOM check, all 2036 maintained file hashes,
paper-bound claim verification, generated Table 6 replacement checks,
`pip check`, source compilation, CSV reproduction, and the upstream-state
check. The tag-workflow contract now requires strict checks and a formal
archive without automatically publishing it. Hosted GitHub Actions has not
been run from this local workspace.

Strict checks intentionally reject the unchanged Table 6 paper timing. The
license gate is closed; the sole remaining gate is
`table6-paper-timing-disagrees-with-raw-results`. No manuscript changes,
commits, pushes, or public upload are part of this preparation.

The candidate builder verifies two byte-identical source snapshots, all
archive members, extracted claims/integrity/tests, and wheel build, license
inclusion, installation, and import. The adjacent archive JSON records the
actual build outcome and hash after these checks succeed. An internal
candidate is not a final public release.

## Delivery validation - 2026-10-20

Validation target: artifact version `0.1.0`. The latest user-designated PDF
replaces the old binding. Final build results are recorded in the adjacent
delivery JSON only after verification succeeds. Checks include the 321-run
MoE dataset, all 179,264 unfinished ages, 106 displayed points, the 150-run
Table 6 replacement, tests, integrity, compilation, and independent
archive rebuild/extraction/wheel checks. A candidate does not close gates.


## Table 6 maintenance validation — 2026-10-20

Artifact version remains `0.1.0.dev0`. Using the existing CPython 3.10.20
verification environment, the maintenance update passed:

- byte-exact verification of all 150 imported raw CSVs against server hashes;
- command/result checks for the full 150-job matrix, recomputation of ten
  runtime aggregates and their reductions, and paper-precision call-count checks;
- independent regeneration of all four archived summary files, with
  byte-for-byte equality;
- all 26 artifact unit tests, including rejection of altered raw bytes and
  an unsupported declared timing value;
- the bound-paper hash check, maintained-file integrity verification,
  publication-safety checks, and deterministic SBOM check;
- the upstream-state check after reviewing the cached paper revision and
  recording the preserved PDF binding.

The Table 6 timing discrepancy, existing MoE discrepancy, and unselected
top-level license remain explicit release gates. No new delivery ZIP is
claimed by this maintenance record; the Git-derived archive builder requires
a clean committed source state.

## Original candidate validation — 2026-09-27

Validation date: 2026-09-27.

The following checks passed for artifact version `0.1.0.dev0`:

- installed the package into a newly created Python 3.11 virtual environment
  with the captured pip/setuptools/wheel versions and `constraints-main.txt`;
  `python -m pip check` reported no broken requirements;
- passed all twenty-four artifact unit tests, including package import, required
  delivery metadata, the
  100,000-slot frame-length evidence contract, Table 6 progress accounting,
  monotonic progress-update safety, a staged Table 6 import contract,
  CI workflow policy, nested-evidence integrity coverage, and
  the current-tree, deleted-history, environment-contract, and third-party
  notice release gates, plus synchronized human- and machine-facing artifact
  version metadata, paper-linked citation metadata, and cross-platform archive
  path safety; the nested LP checksum regression also rejects interpreter and
  packaging caches, and the reproduction-entry regression prevents FIFO plots
  from overwriting immutable evidence; the upstream-state regression detects
  a changed paper without modifying either the paper or its repository;
- independently validated an extracted candidate with CPython 3.10.20 and the
  captured pip 26.0.1, setuptools 82.0.1, and wheel 0.46.3 toolchain: exact
  dependencies installed, `pip check` found no broken requirements, the wheel
  built and installed, `dcnc_sim` imported from that installation, and the full
  test, integrity, and compilation checks passed;
- verified that an empty/placeholder license cannot satisfy the formal release
  gate without complete license text and declared project metadata;
- matched the user-designated latest paper PDF byte-for-byte against the
  SHA-256 identity shared by the claims, MoE audit, and Table 6 audit;
- identified and fingerprinted the parent-paper Git commit and integrated TeX
  source that introduced the MoE table; the verifier independently rules out
  interpolation, per-seed selection, and completed throughput as explanations
  for the two unsupported off-grid FlexMoE values;
- ran a 100-slot `driving_milan` smoke campaign with seeds starting at 1,
  primary interference, and the in-process `exact_dp` solver;
- regenerated all policy-comparison and frame-length plot CSVs from the
  included JSONL evidence;
- recomputed every claim declared `exact` in `manifests/claims.json`;
- verified every maintained file against the artifact SHA-256 manifest;
- completed both the current-tree and full Git-history path/credential safety
  scans with no findings; the history regression fixture proves that content
  committed and later deleted is still rejected without printing its value;
- compiled all first-party Python source files.
- parsed all five maintained Linux shell scripts with `bash -n`; the standard
  `verify_runtime.sh` entry point now repeats this check before its smoke run.
- parsed and contract-tested the read-only GitHub Actions workflow locally; it
  fetches complete history and uses pip constraints machine-checked against the
  captured Conda environment. No hosted CI run is claimed before publication.
- independently generated the Git-derived source ZIP twice and required
  byte-identical output before accepting it; extracted the candidate ZIP into
  a clean directory and repeated claim verification, manifest verification,
  the unit-test suite, and source compilation from the extracted copy; built a
  wheel from that extraction,
  using the pinned setuptools backend without network or build isolation,
  installed it into a separate target, and imported `dcnc_sim` from the
  installed location. The wheel-content gate also prevents the top-level
  license-decision placeholder from being mislabeled as license text and
  requires the selected `LICENSE` inside every formal wheel. The archive
  builder now enforces these clean-room checks for every future candidate and
  formal archive and records its actual interpreter, packaging tools, and
  platform in adjacent machine-readable metadata.
- confirmed the candidate's ZIP members contain no duplicates,
  case-collisions, symbolic links, backslash paths, trailing-dot/space names,
  Windows-reserved path components, interpreter/tool caches, coverage files,
  or generated package metadata; the builder now rejects all of these.
- matched the Table 6 server copies of the core bridge, simulator entry point,
  and command matrix byte-for-byte; all 833 vendored DynVMP source files match
  their remote counterparts, excluding only generated egg-info/cache/log files.
- archived the byte-exact legacy 20k Table 6 summary and mechanically verified
  its relationship to the printed timing values. The near-constant
  topology-specific ratios are recorded as an inference, not accepted as
  provenance; the 100k absolute-time claim remains pending.
- archived the byte-exact manuscript-adjacent Table 6 intermediate and
  mechanically verified its values against the PDF: call counts are close,
  Milan timings match, and Random PDF timings are approximately twice the
  intermediate values. Its untracked status and missing run rows/formula keep
  it classified as a lineage clue, not timing provenance.
- pinned third-party code licenses and research-data provenance in a
  machine-readable manifest. The verifier checks the MIT license files,
  CC-BY-4.0 FlockLab attribution and adaptations, the bundled Topology Zoo
  inventory, and the boundaries of the WfCommons/Pegasus workflow references.
- generated a deterministic SPDX 2.3 SBOM covering the first-party package,
  all 17 pinned Python packages, two vendored source snapshots, and four data
  or workflow sources; the verifier rejects drift from the dependency and
  third-party manifests.

The Python 2 DynVMP bridge was not newly installed on the Windows validation
host. It is being exercised by the active Table 6 server campaign; the vendored
source snapshots and environment definition are included for a clean Linux
installation.

The strict release checks fail intentionally until the blockers documented in
`REPRODUCIBILITY_STATUS.md` are resolved.
