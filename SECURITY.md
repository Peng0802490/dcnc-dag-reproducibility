# Security policy

## Scope

Security reports may cover the first-party simulator, experiment entry points,
release tooling, or a candidate/formal archive produced from this repository.
Vendored components under `third_party/` retain their upstream licenses and
should also be reported to their upstream maintainers when appropriate.

## Reporting

Do not open a public issue for a suspected credential exposure or an
unpublished exploit. Before the public repository exists, contact the paper
authors through an established private correspondence channel. After
publication, prefer the hosting service's private security-advisory mechanism
when it is available. Include the affected commit or archive SHA-256, a minimal
reproduction, impact, and any proposed mitigation. Do not include real secrets
or commercial solver license material in a report or reproduction archive.

## Artifact security boundaries

The artifact does not redistribute Gurobi, a Gurobi license, private keys, or
server credentials. A user who enables the legacy DynVMP path supplies the
commercial solver installation and license outside this repository. Generated
results, local virtual environments, build products, and delivery archives are
ignored by Git.

Run the publication-safety and history checks before sharing any archive:

```bash
python scripts/maintain_artifact.py verify
python scripts/verify_claims.py
```

Formal public archives additionally require both commands to pass with
`--strict`. A candidate archive is explicitly non-public and does not waive
the requirement to avoid credentials or private data.
