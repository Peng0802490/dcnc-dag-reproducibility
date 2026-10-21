# Changelog

## 0.1.0 - 2026-10-20

- Final preparation, 2026-10-21: verify the corrected LaTeX project against
  all 150 Table 6 runs, close the numeric gate at displayed precision, retain
  the old PDF audit, and distinguish source verification from an unverified
  compiled PDF. Preserve manuscript method prose at the owner's request.
- Add pinned source excerpts, tampering regressions, and a detailed Chinese
  GitHub publication walkthrough; no automatic commits, pushes, or upload.
- GitHub preparation, 2026-10-21: install the owner-selected MIT license,
  retain third-party rights notices, and add publication instructions and
  release-note drafts. Publication remains on hold until the paper's Table 6
  is updated, as explicitly requested by the owner.
- Bind the latest designated paper and resolve the obsolete MoE table mismatch.
- Preserve the historical audit; import the complete 321-run latest-figure
  campaign, all 179,264 unfinished ages, and original figure/source snapshots.
- Add independent data verification, redraw and portable rerun commands.
- Generate Table 6 replacement rows and reductions from all 150 raw runs.
- Support deterministic manifest snapshots without committing dirty worktrees.
- Keep pending publication decisions explicit rather than silently clearing gates.

## 0.1.0.dev0 — 2026-09-27

- Maintenance update, 2026-10-20: imported all 150 completed Table 6 result
  CSVs with server SHA-256 verification, a final scheduler capture, generated
  runtime summaries, and regression coverage for evidence tampering. Call
  counts reproduce the paper at its printed precision. Replaced the pending
  campaign gate with an explicit paper/runtime timing mismatch gate.
- Established the single maintained open-source delivery directory.
- Added machine-checked `CITATION.cff` metadata whose artifact version and
  paper title/author order are pinned to the release claims.
- Imported the Python 3 simulator, experiment scripts, exact-DP tools, and the
  Python 2 DynVMP bridge.
- Imported the exact alib and vnep-approx source snapshots used on the server.
- Archived evidence for LP capacity, policy comparisons, Workflow, MoE,
  frame length, and FIFO/NTO experiments.
- Added machine-readable claims, SHA-256 manifests, path/credential scanning,
  and strict release gates.
- Recorded the unresolved MoE mismatch and pending Table 6 campaign instead of
  treating them as reproducible.
- Added auditable Table 6 progress updates and a fail-closed result importer.
- Added gated, Git-derived delivery ZIP construction with in-archive hash
  verification.
- Recomputed MoE thresholds directly from all 504 raw run rows and recorded a
  local/server hash audit showing that no located campaign supports the paper's
  FlexMoE values.
- Added fail-closed clean-room verification of every generated delivery ZIP.
- Rejects Python bytecode, common tool caches, coverage files, and generated
  package metadata from delivery ZIPs even if they are accidentally committed.
- Applies the same generated-file exclusions to the nested LP evidence
  checksum, preventing interpreter-specific cache references from leaking into
  an otherwise portable source archive.
- Runs FIFO/NTO figure reproduction from an isolated `results/fifo/` copy,
  rather than overwriting the archived evidence figures.
- Extended the MoE audit to rule out interpolation and per-seed aggregation as
  explanations for the paper/raw threshold mismatch.
- Identified the exact parent-paper Git commit and integrated TeX source that
  introduced the MoE table, and added raw-data checks that rule out completed
  throughput as an alternative interpretation of its off-grid values.
- Added a read-only, machine-readable upstream-state detector for the pinned
  paper PDF and the parent repository's local and cached remote revisions.
- Added a fail-closed filename gate for private keys, environment files,
  credentials, and commercial solver licenses.
- Archived the exact Table 6 server wrapper, recorded its runtime fingerprint,
  and corrected the installation guide to use the vendored DynVMP sources.
- Added a machine-checked Table 6 timing-provenance audit. It preserves the
  byte-exact legacy 20k summary, detects the unexplained topology-specific
  scaling relationship, and prevents campaign completion alone from being
  mistaken for validation of the paper's absolute timing values.
- Extended publication-safety verification across every blob and pathname in
  Git history, so committing and later deleting a credential, private key,
  machine path, or sensitive filename remains a release-blocking finding.
- Bound candidate builds to the user-designated latest paper PDF when it is
  available in the parent workspace; a changed PDF now blocks stale evidence
  from being packaged, and the build metadata records the binding result.
- Hardened the top-level license gate: formal release now requires substantive
  license text plus non-empty PEP 621 project metadata, rather than accepting
  any file merely named `LICENSE`.
- Archived a byte-exact, untracked manuscript intermediate for Table 6 and
  added machine checks for its close call-count agreement, exact Milan timing
  match, and approximately twofold Random timing relationship. It remains a
  lineage clue rather than accepted raw provenance.
- Added a machine-checked third-party provenance inventory covering the
  vendored MIT dependencies, CC-BY-4.0 FlockLab and Topology Zoo data,
  WfCommons SRA-Search adaptation, and Pegasus SIPHT structural reference.
  Required attribution, transformation notices, hashes, and redistribution
  boundaries now fail closed during integrity verification.
- Added an explicit MoE gate-resolution handoff. It records the missing
  matching manuscript-source lineage and defines the evidence required either
  to correct the paper to the canonical raw results or to retain the printed
  values through a new, independently verified campaign.
- Added a first-party license decision note that recommends MIT for the
  simplest permissive release, explains when Apache-2.0 may be preferable, and
  preserves the separate scope of all third-party licenses and data notices.
- Added a fail-closed environment contract linking `requirements.txt`, PEP 621
  dependencies, exact Conda exports, and the captured Python/Gurobi runtime
  versions, so a partial dependency update cannot silently pass verification.
- Added Linux shell syntax checking to `verify_runtime.sh` and ignored its
  legacy default `results_paper_edge/` output so a successful smoke run cannot
  make the maintained artifact appear dirty.
- Made Table 6 progress updates fail closed against stale timestamps,
  regressing completion/CSV counts, inconsistent totals, and accidental
  campaign-root replacement.
- Added a read-only GitHub Actions integrity workflow with full-history safety
  scanning, a pinned pip verification environment, all artifact tests, shell
  parsing, and clean-room candidate construction.
- Required security, contribution, changelog, and third-party notices in every
  archive, and extended clean-room verification to build, install, and import
  the wheel produced from the extracted delivery ZIP.
- Renamed the top-level license-decision placeholder so packaging tools cannot
  mistake it for selected license text; formal wheel validation now requires
  the actual `LICENSE` and rejects an embedded decision placeholder.
- Made clean-room wheel generation call the pinned PEP 517 setuptools backend
  directly, avoiding pip resolution or network access during archive checks.
- Added a read-only Table 6 scheduler probe and JSON-fed progress updater, so
  future campaign snapshots use structured dispatch/exit evidence, PID
  liveness, log growth, CSV counts, and error scans instead of ad hoc log grep.
- Added a deterministic SPDX 2.3 SBOM generated from the project metadata,
  exact Python constraints, and third-party provenance manifest, with a
  fail-closed regeneration check.
- Made every archive build perform an independent second Git archive pass and
  reject delivery unless both source ZIPs are byte-identical.
- Added a fail-closed artifact-version contract spanning project metadata,
  claims, the current changelog section, validation record, and regenerated
  SBOM identity.
- Recorded the actual interpreter, packaging-tool versions, and platform used
  for each archive's clean-room verification; independently exercised the
  candidate under the captured CPython 3.10.20 environment.
- Fixed the Python 3.10 invalid-escape warning in the virtual-queue service
  documentation string without changing simulator behavior.
- Added fail-closed cross-platform ZIP path validation for duplicates,
  case-collisions, symbolic links, separators, invalid characters, and Windows
  reserved names.
