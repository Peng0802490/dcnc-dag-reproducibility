#!/usr/bin/env python3
"""Read-only detector for paper inputs that may require an artifact update."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def git_revision(repository: Path, revision: str) -> str | None:
    """Resolve one already-local Git revision without fetching or writing."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--verify", revision],
            cwd=repository,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip().lower()
    return value if len(value) == 40 else None


def inspect_upstream_state(
    artifact_root: Path,
    paper_path: Path,
    paper_repository: Path,
) -> dict:
    claims = json.loads(
        (artifact_root / "manifests" / "claims.json").read_text(
            encoding="utf-8"
        )
    )
    source = claims["source_provenance"]
    updates = []
    missing = []

    binding = claims.get("paper_project", claims["paper"])
    input_kind = "paper-project" if "paper_project" in claims else "paper-pdf"
    paper = {
        "filename": binding["filename"],
        "expected_sha256": str(binding["sha256"]).upper(),
        "kind": binding.get("kind", "pdf"),
    }
    if paper_path.is_file():
        paper["observed_sha256"] = sha256(paper_path)
        paper["status"] = (
            "matched"
            if paper["observed_sha256"] == paper["expected_sha256"]
            else "changed"
        )
        if paper["status"] == "changed":
            updates.append(input_kind)
    else:
        paper["status"] = "missing"
        missing.append(input_kind)

    repository = {"status": "unavailable", "refs": {}}
    if (paper_repository / ".git").exists():
        repository["status"] = "available"
        ref_specs = {
            "local_head": ("HEAD", source["paper_repo_local_head"]),
            "cached_origin_master": (
                "refs/remotes/origin/master",
                source["paper_repo_origin_master"],
            ),
        }
        for label, (revision, expected) in ref_specs.items():
            observed = git_revision(paper_repository, revision)
            state = {
                "expected": str(expected).lower(),
                "observed": observed,
            }
            if observed is None:
                state["status"] = "unavailable"
                missing.append(f"paper-repository-{label}")
            elif observed == state["expected"]:
                state["status"] = "matched"
            else:
                state["status"] = "changed"
                updates.append(f"paper-repository-{label}")
            repository["refs"][label] = state
    else:
        missing.append("paper-repository")

    return {
        "schema_version": 1,
        "artifact_version": claims["artifact_version"],
        "paper": paper,
        "paper_repository": repository,
        "update_required": bool(updates),
        "updates": sorted(set(updates)),
        "missing_inputs": sorted(set(missing)),
        "read_only": True,
        "network_accessed": False,
    }


def main() -> int:
    claims = json.loads(
        (ROOT / "manifests" / "claims.json").read_text(encoding="utf-8")
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--paper",
        type=Path,
        default=ROOT.parent / claims.get("paper_project", claims["paper"])["filename"],
    )
    parser.add_argument("--paper-repo", type=Path, default=ROOT.parent)
    parser.add_argument(
        "--fail-on-change",
        action="store_true",
        help="Return exit status 2 when a recorded upstream input changed.",
    )
    parser.add_argument(
        "--require-inputs",
        action="store_true",
        help=(
            "Return exit status 1 when the paper or a recorded Git ref "
            "is unavailable."
        ),
    )
    args = parser.parse_args()
    report = inspect_upstream_state(ROOT, args.paper, args.paper_repo)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.require_inputs and report["missing_inputs"]:
        return 1
    if args.fail_on_change and report["update_required"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
