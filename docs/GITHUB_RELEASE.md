# GitHub publication guide

Publish the extracted artifact as the repository root, not the parent paper
workspace and not a repository containing only a ZIP. The source, evidence,
tests, and hidden `.github/` files must remain together.

Detailed Windows instructions in Chinese: [GITHUB_RELEASE_ZH.md](GITHUB_RELEASE_ZH.md).

For an existing repository, commit the verified update normally and create
the new `v0.1.1` tag. Do not reinitialize history, force-push, retag v0.1.0,
replace its attachments, or change the manuscript's existing v0.1.0 link.

## Publication prerequisites

The owner selected MIT and subsequently supplied the corrected Table 6 source
project. Numerical source alignment is verified; no updated compiled PDF is
claimed. The owner requested release preparation without expanding manuscript
method prose. Both commands must succeed before public publication:

```bash
python scripts/verify_claims.py --strict
python scripts/maintain_artifact.py verify --strict
```

Do not publish any archive whose metadata says `candidate: true`. Do not let
GitHub generate a different license or overwrite the included README.

## Repository contents

| Include | Purpose |
|---|---|
| `src/`, `scripts/`, `tools/` | Simulator, experiment runners, aggregation, plots, verification |
| `inputs/` | Organized topology, DAG, configuration, and protocol inputs |
| `evidence/` | Paper-relevant per-run outputs, summaries, provenance, and corrections |
| `third_party/`, `THIRD_PARTY.md` | Pinned dependencies and retained third-party rights notices |
| Environment files and `pyproject.toml` | Installation and reproducible dependency versions |
| `.github/`, `tests/`, `manifests/`, checksums, SBOM | CI, regression tests, and integrity checks |
| README, citation, license, release notes, `docs/` | Usage, attribution, scope, and publication instructions |

Never copy the parent paper repository, its `.git/`, private review notes,
Overleaf configuration, server credentials, Gurobi license, installed runtimes,
or the working `results/`, `build/`, and `dist/` directories. The bound paper
PDF is identified by hash and is not redistributed in this package.

## Create the repository

Suggested repository name: `dcnc-dag-reproducibility`.

Suggested description:

> Simulator, experiment data, and reproducibility tools for Throughput-Optimal
> Control of Distributed Computing Networks for Service DAGs.

Use GitHub Desktop or Git from an extracted, verified formal archive. Create
an empty repository without an automatically generated README, license, or
gitignore. A fresh history avoids publishing the paper workspace history.
Using a private repository first allows checking hosted CI before making it
public. Enable private vulnerability reporting in the repository settings.

The following commands are for the repository owner to run; preparation does
not execute them or publish anything. Replace
`OWNER` with the actual GitHub account or organization. Run them inside the
extracted artifact, where `README.md` and `src/` are directly visible:

```bash
git init -b main
git add .
git diff --cached --stat
git status --short
git commit -m "Release DCNC-DAG reproducibility artifact 0.1.1"
git remote add origin https://github.com/OWNER/dcnc-dag-reproducibility.git
git push -u origin main
```

Review staged files before committing. Do not use GitHub's browser upload for
this multi-thousand-file package: it is easy to omit dotfiles or only upload
part of the evidence. There is no need to upload a Python environment or use
Git LFS for the current artifact.

## Create the GitHub release

1. Wait for the `Artifact integrity` workflow on the source commit to pass.
2. Re-run both strict commands above. Tag that verified commit `v0.1.1` and
   push only that tag. The tag workflow additionally requires a formal build.
3. Wait for the tag workflow to pass; this is not automatic publication.
4. In GitHub Releases, select `v0.1.1`, use title `DCNC-DAG reproducibility
   artifact v0.1.1`, and paste the reviewed text from `RELEASE_NOTES.md`.
5. Attach the formal `.zip`, its `.zip.sha256`, and its `.zip.json` together.
   Do not attach an old candidate or confuse GitHub's automatic source ZIP
   with the separately verified delivery archive.

If using a locally prepared manifest snapshot, its metadata intentionally
records a base commit rather than pretending the uncommitted snapshot was
already a commit. Commit exactly the extracted files, without newline changes
or extra files, to make the initial public source match that snapshot. A
subsequent release should be rebuilt from its own clean, reviewed commit.

## Reader verification

After extracting the ZIP, check its adjacent SHA-256 before running code:

```powershell
Get-FileHash ./dcnc-dag-reproducibility-0.1.1.zip -Algorithm SHA256
```

On Linux, `sha256sum -c dcnc-dag-reproducibility-0.1.1.zip.sha256` performs
the comparison directly. From the extracted directory, the claim and file
verification commands use only Python's standard library; install the pinned
environment before running tests or plotting.
