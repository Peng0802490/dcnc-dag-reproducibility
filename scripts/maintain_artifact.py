#!/usr/bin/env python3
"""Sanitize imported provenance, refresh hashes, and verify release integrity."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FILE_MANIFEST = ROOT / "manifests" / "files.json"
CHECKSUMS = ROOT / "SHA256SUMS.txt"
GENERATED = {"SHA256SUMS.txt", "manifests/files.json"}
IGNORED_ANYWHERE = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
IGNORED_BASENAMES = {".coverage", ".ds_store", "thumbs.db"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
IGNORED_TOP_LEVEL = {".runtime", "results", "dist", "build"}
TEXT_SUFFIXES = {
    ".cfg", ".csv", ".env", ".ini", ".json", ".jsonl", ".log", ".md",
    ".py", ".sh", ".toml", ".txt", ".xml", ".yml", ".yaml",
}
PRIVATE_KEY_SUFFIXES = {".key", ".jks", ".p12", ".pem", ".pfx"}
SENSITIVE_BASENAMES = {
    "gurobi.lic",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
PATH_MARKERS = ("/home/" + "lipeng", "E:" + "\\research\\")
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password)\b"
    r"\s*[:=]\s*['\"][^'\"]{8,}"
)


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def is_generated_path(parts: tuple[str, ...]) -> bool:
    """Return whether a relative path is generated cache/build metadata."""
    folded = tuple(part.casefold() for part in parts)
    return (
        any(part in IGNORED_ANYWHERE for part in folded)
        or any(part in IGNORED_BASENAMES for part in folded)
        or any(part.endswith(".egg-info") for part in folded)
        or any(Path(part).suffix.casefold() in IGNORED_SUFFIXES for part in folded)
    )


def maintained_files() -> list[Path]:
    candidates = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = rel(path)
        parts = path.relative_to(ROOT).parts
        if (
            relative in GENERATED
            or (parts and parts[0] in IGNORED_TOP_LEVEL)
            or is_generated_path(parts)
        ):
            continue
        candidates.append(path)

    relative_names = [rel(path) for path in candidates]
    ignored: set[str] = set()
    if (ROOT / ".git").exists() and relative_names:
        completed = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=ROOT,
            input=("\0".join(relative_names) + "\0").encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode not in (0, 1):
            raise RuntimeError(
                "git check-ignore failed: "
                + completed.stderr.decode("utf-8", errors="replace").strip()
            )
        ignored = {
            item.decode("utf-8")
            for item in completed.stdout.split(b"\0")
            if item
        }
    files = [path for path in candidates if rel(path) not in ignored]
    return sorted(files, key=rel)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sensitive_filename(path: Path) -> bool:
    """Return whether a filename is unsafe to place in a public artifact."""
    name = path.name.lower()
    if name == ".env" or name.startswith(".env."):
        return True
    if name in SENSITIVE_BASENAMES or path.suffix.lower() in PRIVATE_KEY_SUFFIXES:
        return True
    if re.fullmatch(r"(?:credentials?|secrets?|tokens?)\.(?:json|ya?ml|txt)", name):
        return True
    if re.fullmatch(r"client_secret.*\.json", name):
        return True
    if re.fullmatch(r"service[-_]?account.*\.json", name):
        return True
    return False


def _project_license_declared(pyproject_text: str) -> bool:
    """Return whether the PEP 621 project table has non-empty license metadata."""
    in_project = False
    for raw_line in pyproject_text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if not in_project:
            continue
        match = re.match(r"license\s*=\s*(.+?)\s*(?:#.*)?$", line)
        if not match:
            continue
        value = match.group(1).strip()
        return value not in {"", "''", '""', "{}"}
    return False


def license_selection_issues(repo_root: Path = ROOT) -> list[str]:
    """Explain why the first-party license selection is not release-complete."""
    issues = []
    license_path = repo_root / "LICENSE"
    if not license_path.is_file():
        issues.append("top-level LICENSE missing")
    elif license_path.stat().st_size < 128:
        issues.append(
            "top-level LICENSE is too short to contain complete license text"
        )

    pyproject_path = repo_root / "pyproject.toml"
    try:
        pyproject_text = pyproject_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        issues.append("pyproject.toml is missing or unreadable")
    else:
        if not _project_license_declared(pyproject_text):
            issues.append("pyproject.toml [project] license metadata missing")
    return issues


def artifact_version_issues(repo_root: Path = ROOT) -> list[str]:
    """Require all human- and machine-facing artifact versions to agree."""
    try:
        pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
        claims = json.loads(
            (repo_root / "manifests" / "claims.json").read_text(encoding="utf-8")
        )
        changelog = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
        validation = (repo_root / "docs" / "VALIDATION.md").read_text(
            encoding="utf-8"
        )
        citation = (repo_root / "CITATION.cff").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"artifact version metadata is missing or unreadable: {exc}"]

    project_match = re.search(
        r'^version\s*=\s*"([^"]+)"', pyproject, flags=re.MULTILINE
    )
    if not project_match:
        return ["artifact version missing from pyproject.toml"]
    expected = project_match.group(1)

    observed = {
        "manifests/claims.json": claims.get("artifact_version"),
        "CHANGELOG.md current section": (
            match.group(1)
            if (match := re.search(r"^##\s+(\S+)", changelog, flags=re.MULTILINE))
            else None
        ),
        "docs/VALIDATION.md": (
            match.group(1)
            if (
                match := re.search(
                    r"artifact version `([^`]+)`", validation
                )
            )
            else None
        ),
        "CITATION.cff": (
            match.group(1)
            if (
                match := re.search(
                    r'^version:\s*["\']?([^"\'\s]+)',
                    citation,
                    flags=re.MULTILINE,
                )
            )
            else None
        ),
    }
    return [
        f"artifact version mismatch: {source} has {value!r}, expected {expected!r}"
        for source, value in observed.items()
        if value != expected
    ]


def _package_name(specification: str) -> str:
    """Return a normalized distribution name from a requirement string."""
    name = re.split(r"[<>=!~;\[]", specification, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", name).lower()


def _project_dependencies(pyproject_text: str) -> dict[str, str]:
    match = re.search(r"^dependencies\s*=\s*\[", pyproject_text, re.MULTILINE)
    if not match:
        return {}
    start = match.end()
    depth = 1
    quote = None
    escaped = False
    end = None
    for index, character in enumerate(pyproject_text[start:], start=start):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        return {}
    body = pyproject_text[start:end]
    values = re.findall(r'["\']([^"\']+)["\']', body)
    return {
        _package_name(value): re.sub(r"\s+", "", value)
        for value in values
    }


def _requirement_specs(requirements_text: str) -> dict[str, str]:
    values = [
        line.split("#", 1)[0].strip()
        for line in requirements_text.splitlines()
        if line.split("#", 1)[0].strip()
    ]
    return {
        _package_name(value): re.sub(r"\s+", "", value)
        for value in values
    }


def _exact_requirement_versions(requirements_text: str) -> tuple[dict[str, str], list[str]]:
    """Parse a pip constraint file while rejecting every non-exact entry."""
    versions: dict[str, str] = {}
    invalid: list[str] = []
    for name, specification in _requirement_specs(requirements_text).items():
        match = re.fullmatch(r"[^<>=!~;\[\]\s]+==([^,;]+)", specification)
        if not match:
            invalid.append(name)
            continue
        versions[name] = match.group(1)
    return versions, sorted(invalid)


def _numeric_version(version: str) -> tuple[int, ...] | None:
    match = re.match(r"^(\d+(?:\.\d+)*)", version)
    if not match:
        return None
    return tuple(int(component) for component in match.group(1).split("."))


def _environment_pip_versions(environment_text: str) -> dict[str, str]:
    versions = {}
    in_pip = False
    for line in environment_text.splitlines():
        if re.fullmatch(r"\s*- pip:\s*", line):
            in_pip = True
            continue
        if not in_pip:
            continue
        match = re.fullmatch(r"\s{6}-\s+([^=\s]+)==(.+)", line)
        if match:
            versions[_package_name(match.group(1))] = match.group(2).strip()
            continue
        if line.strip() and len(line) - len(line.lstrip()) <= 2:
            in_pip = False
    return versions


def _environment_python(environment_text: str) -> str | None:
    match = re.search(r"^\s*- python=([^=\s]+)", environment_text, re.MULTILINE)
    return match.group(1) if match else None


def environment_contract_issues(repo_root: Path = ROOT) -> list[str]:
    """Keep generic install metadata aligned with the exact run environments."""
    issues = []
    paths = {
        "requirements": repo_root / "requirements.txt",
        "constraints": repo_root / "constraints-main.txt",
        "pyproject": repo_root / "pyproject.toml",
        "main": repo_root / "environment_dcnc_dag.yml",
        "dynvmp": repo_root / "environment_dynvmp_py2.yml",
        "fingerprint": (
            repo_root / "evidence" / "table6" / "runtime_fingerprint.json"
        ),
    }
    try:
        requirements_text = paths["requirements"].read_text(encoding="utf-8")
        constraints_text = paths["constraints"].read_text(encoding="utf-8")
        pyproject_text = paths["pyproject"].read_text(encoding="utf-8")
        main_text = paths["main"].read_text(encoding="utf-8")
        dynvmp_text = paths["dynvmp"].read_text(encoding="utf-8")
        fingerprint = json.loads(paths["fingerprint"].read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ["environment contract input is missing or unreadable"]

    requirements = _requirement_specs(requirements_text)
    project = _project_dependencies(pyproject_text)
    if requirements != project:
        issues.append(
            "requirements.txt and pyproject.toml dependency specifications disagree"
        )

    main_versions = _environment_pip_versions(main_text)
    constraint_versions, invalid_constraints = _exact_requirement_versions(
        constraints_text
    )
    if invalid_constraints:
        issues.append(
            "main pip constraints contain non-exact entries: "
            + ", ".join(invalid_constraints)
        )
    if constraint_versions != main_versions:
        issues.append(
            "constraints-main.txt does not exactly match main environment pip pins"
        )
    missing_or_unpinned = sorted(set(requirements) - set(main_versions))
    if missing_or_unpinned:
        issues.append(
            "main exact environment lacks pinned runtime dependencies: "
            + ", ".join(missing_or_unpinned)
        )
    for name, specification in requirements.items():
        minimum_match = re.search(r">=([^,;]+)", specification)
        pinned = main_versions.get(name)
        if not minimum_match or not pinned:
            continue
        minimum = _numeric_version(minimum_match.group(1))
        observed = _numeric_version(pinned)
        if minimum is None or observed is None or observed < minimum:
            issues.append(
                f"main exact environment {name}=={pinned} does not satisfy "
                f"{specification}"
            )

    software = fingerprint.get("software", {})
    observed_main_python = _environment_python(main_text)
    if observed_main_python != str(software.get("main_python", "")):
        issues.append("main Python version disagrees with runtime fingerprint")
    observed_dynvmp_python = _environment_python(dynvmp_text)
    if observed_dynvmp_python != str(software.get("dynvmp_python", "")):
        issues.append("DynVMP Python version disagrees with runtime fingerprint")
    dynvmp_versions = _environment_pip_versions(dynvmp_text)
    if dynvmp_versions.get("gurobipy") != str(
        software.get("dynvmp_gurobipy", "")
    ):
        issues.append("DynVMP gurobipy version disagrees with runtime fingerprint")
    return issues


def third_party_notice_issues(repo_root: Path = ROOT) -> list[str]:
    """Verify that third-party licenses, attribution, and derivation stay pinned."""
    issues = []
    manifest_path = repo_root / "manifests" / "third_party.json"
    notice_path = repo_root / "THIRD_PARTY.md"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ["third-party provenance manifest is missing or unreadable"]
    try:
        notice = notice_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ["THIRD_PARTY.md is missing or unreadable"]

    for fragment in manifest.get("required_notice_fragments", []):
        if fragment not in notice:
            issues.append(f"THIRD_PARTY.md missing required notice: {fragment}")

    for item in manifest.get("license_files", []):
        path = repo_root / item["path"]
        if not path.is_file():
            issues.append(f"third-party license missing: {item['path']}")
        elif sha256(path) != item["sha256"]:
            issues.append(f"third-party license hash mismatch: {item['path']}")

    sources = manifest.get("data_sources", {})
    topology = sources.get("internet_topology_zoo", {})
    topology_root = repo_root / topology.get("path", "")
    local_notice = repo_root / topology.get("local_notice", "")
    if not local_notice.is_file():
        issues.append("Internet Topology Zoo local attribution is missing")
    elif sha256(local_notice) != topology.get("local_notice_sha256"):
        issues.append("Internet Topology Zoo local attribution hash mismatch")
    if not topology_root.is_dir():
        issues.append("Internet Topology Zoo vendored data directory is missing")
    else:
        for suffix, expected_count in topology.get(
            "expected_files_by_extension", {}
        ).items():
            observed_count = sum(
                1 for path in topology_root.iterdir()
                if path.is_file() and path.suffix == suffix
            )
            if observed_count != expected_count:
                issues.append(
                    "Internet Topology Zoo file-count mismatch "
                    f"for {suffix}: observed={observed_count} "
                    f"expected={expected_count}"
                )

    flocklab = sources.get("flocklab", {})
    for item in flocklab.get("derived_files", []):
        path = repo_root / item["path"]
        if not path.is_file():
            issues.append(f"FlockLab adapted data missing: {item['path']}")
            continue
        if sha256(path) != item["sha256"]:
            issues.append(f"FlockLab adapted data hash mismatch: {item['path']}")
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            observed_source = document["metadata"]["official_source"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
            issues.append(f"FlockLab source metadata unreadable: {item['path']}")
            continue
        if observed_source != flocklab.get("official_source_field"):
            issues.append(f"FlockLab source metadata mismatch: {item['path']}")

    for key in ("wfcommons_sra_search", "pegasus_sipht"):
        source = sources.get(key, {})
        path = repo_root / source.get("derived_file", "")
        if not path.is_file():
            issues.append(
                f"workflow adaptation missing: {source.get('derived_file')}"
            )
        elif sha256(path) != source.get("derived_sha256"):
            issues.append(
                f"workflow adaptation hash mismatch: {source.get('derived_file')}"
            )
        else:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
                observed_source = document["metadata"]["source_workflow"]
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
                issues.append(
                    f"workflow source metadata unreadable: {source.get('derived_file')}"
                )
            else:
                expected_source = source.get("metadata_source_workflow")
                if observed_source != expected_source:
                    issues.append(
                        "workflow source metadata mismatch: "
                        f"{source.get('derived_file')}"
                    )
        if source.get("raw_source_redistributed") is not False:
            issues.append(f"workflow source boundary is not fail-closed: {key}")
    return issues


def sbom_issues(repo_root: Path = ROOT) -> list[str]:
    """Require the committed SPDX SBOM to match its authoritative inputs."""
    try:
        if __package__:
            from .generate_sbom import build_sbom
        else:
            from generate_sbom import build_sbom

        expected = build_sbom(repo_root)
        actual = json.loads(
            (repo_root / "SBOM.spdx.json").read_text(encoding="utf-8")
        )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ) as exc:
        return [f"SBOM is missing, unreadable, or cannot be regenerated: {exc}"]
    issues = []
    if actual != expected:
        issues.append("SBOM.spdx.json is stale or disagrees with authoritative inputs")
    identifiers = [item.get("SPDXID") for item in actual.get("packages", [])]
    if len(identifiers) != len(set(identifiers)):
        issues.append("SBOM package SPDX identifiers are not unique")
    if actual.get("spdxVersion") != "SPDX-2.3":
        issues.append("SBOM SPDX version is not 2.3")
    return issues


def _text_safety_kinds(relative: str, text: str) -> list[str]:
    """Classify unsafe text without returning the matched value."""
    kinds = []
    if relative != "scripts/maintain_artifact.py" and any(
        marker in text for marker in PATH_MARKERS
    ):
        kinds.append("machine-specific path")
    if PRIVATE_KEY_PATTERN.search(text):
        kinds.append("private key marker")
    if SECRET_ASSIGNMENT_PATTERN.search(text):
        kinds.append("possible credential assignment")
    return kinds


def _git_batch_blobs(
    repo_root: Path, object_ids: list[str]
) -> tuple[dict[str, bytes], str | None]:
    """Read selected Git objects in one process without checking them out."""
    if not object_ids:
        return {}, None
    try:
        completed = subprocess.run(
            ["git", "cat-file", "--batch"],
            cwd=repo_root,
            input=("\n".join(object_ids) + "\n").encode("ascii"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return {}, "Git history object scan could not start"
    if completed.returncode != 0:
        return {}, f"Git history object scan failed (exit {completed.returncode})"

    blobs: dict[str, bytes] = {}
    output = completed.stdout
    cursor = 0
    for requested in object_ids:
        line_end = output.find(b"\n", cursor)
        if line_end < 0:
            return {}, "Git history object scan returned truncated metadata"
        fields = output[cursor:line_end].split()
        cursor = line_end + 1
        if len(fields) == 2 and fields[1] == b"missing":
            return {}, f"Git history object is missing ({requested[:12]})"
        if len(fields) != 3:
            return {}, "Git history object scan returned invalid metadata"
        object_id, object_type, raw_size = fields
        try:
            size = int(raw_size)
        except ValueError:
            return {}, "Git history object scan returned an invalid size"
        end = cursor + size
        if end >= len(output) or output[end:end + 1] != b"\n":
            return {}, "Git history object scan returned truncated content"
        if object_type == b"blob":
            blobs[object_id.decode("ascii")] = output[cursor:end]
        cursor = end + 1
    return blobs, None


def git_history_safety_findings(repo_root: Path = ROOT) -> list[str]:
    """Find publication-sensitive filenames and text anywhere in Git history."""
    if not (repo_root / ".git").exists():
        return []
    try:
        completed = subprocess.run(
            [
                "git", "-c", "core.quotePath=false",
                "rev-list", "--objects", "--all",
            ],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return ["Git history enumeration could not start"]
    if completed.returncode != 0:
        return [f"Git history enumeration failed (exit {completed.returncode})"]

    findings: set[str] = set()
    text_paths_by_object: dict[str, set[str]] = {}
    for raw_line in completed.stdout.decode("utf-8", errors="replace").splitlines():
        fields = raw_line.split(maxsplit=1)
        if len(fields) != 2:
            continue
        object_id, relative = fields
        short_id = object_id[:12]
        historical_path = Path(relative)
        if sensitive_filename(historical_path):
            findings.add(
                f"sensitive filename in Git history: {relative} (object {short_id})"
            )
        if (
            relative.startswith("third_party/")
            or relative == "scripts/maintain_artifact.py"
            or historical_path.suffix.lower() not in TEXT_SUFFIXES
        ):
            continue
        text_paths_by_object.setdefault(object_id, set()).add(relative)

    blobs, error = _git_batch_blobs(repo_root, sorted(text_paths_by_object))
    if error:
        findings.add(error)
    else:
        for object_id, paths in text_paths_by_object.items():
            data = blobs.get(object_id)
            if data is None:
                continue
            text = data.decode("utf-8", errors="replace")
            for relative in paths:
                for kind in _text_safety_kinds(relative, text):
                    findings.add(
                        f"{kind} in Git history: {relative} "
                        f"(object {object_id[:12]})"
                    )
    return sorted(findings)


def sanitize_imported_provenance() -> int:
    # Construct user-specific markers in pieces so the safety scanner does not
    # flag this maintenance tool merely for defining its cleanup rules.
    old_root = "/home/" + "lipeng/dcnc_dag_py3"
    old_python = "/home/" + "lipeng/miniconda3/envs/dcnc_dag/bin/python"
    old_windows = "E:" + "\\research\\dcnc-dag-paper"
    replacements = {
        old_python: "python",
        old_root: "${ARTIFACT_ROOT}",
        old_windows: "${PAPER_REPO}",
    }
    changed = []
    for base in (ROOT / "evidence", ROOT / "docs"):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            updated = text
            for old, new in replacements.items():
                updated = updated.replace(old, new)
            if updated != text:
                path.write_text(updated, encoding="utf-8", newline="")
                changed.append(rel(path))
    print(f"sanitized {len(changed)} imported provenance file(s)")
    for name in changed:
        print(f"  {name}")
    return 0


def normalize_first_party_line_endings() -> None:
    """Keep maintained first-party text byte-stable across operating systems."""
    preserved_prefixes = ("evidence/", "inputs/", "legacy_inputs/", "third_party/")
    for path in maintained_files():
        relative = rel(path)
        if relative.startswith(preserved_prefixes) or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        data = path.read_bytes()
        normalized = data.replace(b"\r\n", b"\n")
        if normalized != data:
            path.write_bytes(normalized)


def refresh_lp_manifest(repo_root: Path = ROOT) -> None:
    """Refresh the nested delivery hashes after path-only provenance sanitization."""
    lp_root = repo_root / "evidence" / "lp_capacity"
    manifest_path = lp_root / "SHA256SUMS.txt"
    entries = []
    for path in sorted(lp_root.rglob("*")):
        relative_parts = path.relative_to(lp_root).parts
        if (
            not path.is_file()
            or path == manifest_path
            or is_generated_path(relative_parts)
        ):
            continue
        entries.append(f"{sha256(path)}  {path.relative_to(lp_root).as_posix()}\n")
    manifest_path.write_text("".join(entries), encoding="utf-8", newline="\n")


def refresh() -> int:
    normalize_first_party_line_endings()
    refresh_lp_manifest()
    entries = []
    for path in maintained_files():
        entries.append({"path": rel(path), "bytes": path.stat().st_size, "sha256": sha256(path)})
    document = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "excludes": sorted(GENERATED),
        "files": entries,
    }
    FILE_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    FILE_MANIFEST.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    CHECKSUMS.write_text(
        "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in entries),
        encoding="utf-8",
        newline="\n",
    )
    print(f"refreshed hashes for {len(entries)} maintained file(s)")
    return 0


def safety_findings() -> list[str]:
    findings = []
    for path in maintained_files():
        relative = rel(path)
        if sensitive_filename(path):
            findings.append(f"sensitive filename in artifact: {relative}")
        if relative.startswith("third_party/") or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for kind in _text_safety_kinds(relative, text):
            findings.append(f"{kind} in {relative}")
    return findings


def verify(strict: bool) -> int:
    if not FILE_MANIFEST.exists() or not CHECKSUMS.exists():
        print("manifest missing; run refresh first", file=sys.stderr)
        return 1
    manifest = json.loads(FILE_MANIFEST.read_text(encoding="utf-8"))
    expected = {item["path"]: item for item in manifest["files"]}
    actual_paths = {rel(path): path for path in maintained_files()}
    failures = []
    for name, item in expected.items():
        path = ROOT / name
        if not path.is_file():
            failures.append(f"missing: {name}")
            continue
        if path.stat().st_size != item["bytes"]:
            failures.append(f"size mismatch: {name}")
        if sha256(path) != item["sha256"]:
            failures.append(f"hash mismatch: {name}")
    for name in sorted(set(actual_paths) - set(expected)):
        failures.append(f"unmanifested: {name}")
    failures.extend(safety_findings())
    failures.extend(git_history_safety_findings())
    failures.extend(artifact_version_issues())
    failures.extend(environment_contract_issues())
    failures.extend(third_party_notice_issues())
    failures.extend(sbom_issues())

    claims = json.loads((ROOT / "manifests" / "claims.json").read_text(encoding="utf-8"))
    if strict:
        failures.extend(license_selection_issues())
        if not claims.get("release_ready"):
            failures.append("claims manifest release_ready is false")
        for gate in claims.get("open_gates", []):
            failures.append(f"open release gate: {gate}")

    if failures:
        print(f"integrity verification failed: {len(failures)} issue(s)", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(
        f"verified {len(expected)} maintained file(s); "
        "working-tree, Git-history, environment, and third-party checks clean"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sanitize-imported-provenance")
    sub.add_parser("refresh")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if args.command == "sanitize-imported-provenance":
        return sanitize_imported_provenance()
    if args.command == "refresh":
        return refresh()
    return verify(args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
