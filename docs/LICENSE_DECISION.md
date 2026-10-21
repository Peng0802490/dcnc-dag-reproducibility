# First-party license decision

The owner selected **MIT** on 2026-10-21. The complete license is in `LICENSE`;
`pyproject.toml` declares the SPDX expression `MIT` and includes the license
in built distributions. The license-selection release gate is closed.

## Scope

MIT applies to original first-party software, configurations, documentation,
and accompanying experimental material in this artifact to the extent the
DCNC-DAG rights holders can license that material. It does not grant rights
over someone else's work or replace any third-party terms.

`THIRD_PARTY.md` and `manifests/third_party.json` identify vendored code,
external datasets, adaptations, and retained notices. In particular, vendored
alib and vnep-approx code retain their original MIT notices; Topology Zoo and
FlockLab data retain their CC-BY-4.0 attribution requirements. The workflow
structure provenance and Pegasus Gallery scope caveat remain documented.

Gurobi and its license are not redistributed. Neither the manuscript PDF nor
the parent paper workspace is licensed or included by this artifact release.
Paper citation metadata is not a grant of publication rights over the paper.

## Publication status

License selection does not itself authorize a public upload. The corrected
source project has now been verified and the owner requested release
preparation. No manuscript method expansion or automatic GitHub upload is
performed; see `REPRODUCIBILITY_STATUS.md` for the source-verification scope.
