# Updating this artifact

Keep raw evidence immutable. Import a new campaign into a new or existing
`evidence/<claim>/` directory, retaining its command matrix and aggregation
script. Never overwrite a contradictory result silently.

For every update:

1. Inspect `git status` and update the artifact checkout before editing.
   Maintainers with the separate parent paper repository should also refresh
   its cached refs with `git fetch origin`, then run
   `python scripts/check_upstream_state.py --require-inputs --fail-on-change`.
   Review reported changes before importing; the detector is read-only and
   never fetches by itself. A standalone GitHub checkout does not require
   access to the private paper workspace.
2. Record the protocol, seeds, horizon, solver, and source location in
   `manifests/claims.json`.
3. Sanitize only machine-specific provenance paths with
   `python scripts/maintain_artifact.py sanitize-imported-provenance`.
4. Update the claim verifier when a paper-facing number changes.
5. Run `python scripts/verify_claims.py` and the unit tests.
6. Run `python scripts/maintain_artifact.py refresh` followed by
   `python scripts/maintain_artifact.py verify`.
7. Before publication, run both commands with `--strict` and require success.
8. Build the public ZIP with `python scripts/build_release_archive.py`; do not
   rename a `candidate` ZIP into a release.

Do not add credentials, Gurobi license files, private keys, generated caches,
or machine-specific absolute paths.
