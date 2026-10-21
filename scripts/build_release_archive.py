#!/usr/bin/env python3
"""Build and verify a Git-derived final or explicitly marked candidate archive."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ARCHIVE_FILES = {
    "CHANGELOG.md",
    "CITATION.cff",
    "CONTRIBUTING.md",
    "README.md",
    "RELEASE_NOTES.md",
    "REPRODUCIBILITY_STATUS.md",
    "SECURITY.md",
    "SHA256SUMS.txt",
    "SBOM.spdx.json",
    "THIRD_PARTY.md",
    "constraints-main.txt",
    "environment_dcnc_dag.yml",
    "manifests/claims.json",
    "manifests/files.json",
    "pyproject.toml",
    "docs/GITHUB_RELEASE.md",
    "scripts/check_upstream_state.py",
    "scripts/maintain_artifact.py",
    "scripts/table6_progress_probe.py",
    "scripts/update_table6_progress.py",
    "scripts/verify_claims.py",
    "scripts/verify_paper_update.py",
}
WINDOWS_RESERVED_STEMS = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
GENERATED_ARCHIVE_COMPONENTS = {
    ".coverage",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".ds_store",
    "thumbs.db",
}
GENERATED_ARCHIVE_SUFFIXES = {".pyc", ".pyo"}


def run_checked(
    command: list[str], *, cwd: Path = ROOT, capture: bool = False
) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=False,
    )
    if completed.returncode != 0:
        if capture and completed.stdout:
            print(completed.stdout, file=sys.stderr, end="")
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}")
    return (completed.stdout or "").strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("could not read project version from pyproject.toml")
    return match.group(1)


def verification_runtime() -> dict[str, str]:
    """Return non-secret runtime identity for the archive verification process."""
    distributions = {}
    for name in ("pip", "setuptools", "wheel"):
        try:
            distributions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            distributions[name] = "not-installed"
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "system_release": platform.release(),
        "machine": platform.machine(),
        **distributions,
    }


def validate_archive_member(member: zipfile.ZipInfo, prefix: str) -> None:
    """Reject a ZIP member that is unsafe or not cross-platform portable."""
    name = member.filename
    if "\\" in name:
        raise RuntimeError(f"archive member contains a backslash: {name}")
    parsed = PurePosixPath(name)
    if parsed.is_absolute() or ".." in parsed.parts or not name.startswith(prefix):
        raise RuntimeError(f"unsafe archive member: {name}")
    if stat.S_ISLNK((member.external_attr >> 16) & 0xFFFF):
        raise RuntimeError(f"archive contains a symbolic link: {name}")
    for component in parsed.parts[1:]:
        folded_component = component.casefold()
        if (
            folded_component in GENERATED_ARCHIVE_COMPONENTS
            or PurePosixPath(component).suffix.casefold()
            in GENERATED_ARCHIVE_SUFFIXES
            or folded_component.endswith(".egg-info")
        ):
            raise RuntimeError(
                f"archive contains generated build/cache material: {name}"
            )
        if component.endswith((".", " ")):
            raise RuntimeError(f"archive member is not Windows-portable: {name}")
        if re.search(r'[<>:"|?*\x00-\x1f]', component):
            raise RuntimeError(
                f"archive member contains a Windows-invalid character: {name}"
            )
        stem = component.split(".", 1)[0].casefold()
        if stem in WINDOWS_RESERVED_STEMS:
            raise RuntimeError(
                f"archive member uses a Windows-reserved name: {name}"
            )


def validate_archive(
    path: Path, prefix: str, *, require_license: bool
) -> tuple[int, int]:
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [member.filename for member in members]
        name_set = set(names)
        if len(names) != len(name_set):
            raise RuntimeError("archive contains duplicate member names")
        casefolded = {}
        for name in names:
            folded = name.casefold()
            previous = casefolded.setdefault(folded, name)
            if previous != name:
                raise RuntimeError(
                    f"archive contains case-colliding members: {previous}, {name}"
                )

        for member in members:
            validate_archive_member(member, prefix)
            relative_parts = PurePosixPath(member.filename).parts[1:]
            hidden_runtime = any(
                part in {".git", ".runtime"} for part in relative_parts
            )
            generated_top_level = bool(
                relative_parts and relative_parts[0] in {"results", "dist", "build"}
            )
            if hidden_runtime or generated_top_level:
                raise RuntimeError(
                    f"forbidden archive member: {member.filename}"
                )

        required = set(REQUIRED_ARCHIVE_FILES)
        if require_license:
            required.add("LICENSE")
        missing = sorted(item for item in required if prefix + item not in name_set)
        if missing:
            raise RuntimeError(f"archive is missing required files: {missing}")

        checksum_member = prefix + "SHA256SUMS.txt"
        checksum_lines = archive.read(checksum_member).decode("utf-8").splitlines()
        verified = 0
        for line in checksum_lines:
            if not line.strip():
                continue
            expected, relative = line.split("  ", 1)
            member = prefix + relative
            if member not in name_set:
                raise RuntimeError(f"manifested file missing from archive: {relative}")
            observed = sha256_bytes(archive.read(member))
            if observed != expected:
                raise RuntimeError(f"archive hash mismatch: {relative}")
            verified += 1
        return len(names), verified


def validate_extracted_archive(path: Path, prefix: str, *, strict: bool) -> None:
    """Run the standard verification suite from a clean archive extraction."""
    with tempfile.TemporaryDirectory(prefix="dcnc-dag-archive-") as temp_name:
        temp_root = Path(temp_name)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(temp_root)
        extracted_root = temp_root / prefix.rstrip("/")
        gate_suffix = ["--strict"] if strict else []
        commands = [
            [sys.executable, "scripts/verify_claims.py", *gate_suffix],
            [
                sys.executable,
                "scripts/maintain_artifact.py",
                "verify",
                *gate_suffix,
            ],
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            [sys.executable, "-m", "compileall", "-q", "src", "scripts", "tests"],
        ]
        for command in commands:
            run_checked(command, cwd=extracted_root, capture=True)

        wheelhouse = temp_root / "wheelhouse"
        wheelhouse.mkdir()
        backend_command = (
            "import sys; "
            "from pathlib import Path; "
            "from setuptools import build_meta; "
            "destination = Path(sys.argv[1]).resolve(); "
            "wheel = build_meta.build_wheel(str(destination)); "
            "assert (destination / wheel).is_file(); "
            "print(wheel)"
        )
        run_checked(
            [
                sys.executable,
                "-c",
                backend_command,
                str(wheelhouse),
            ],
            cwd=extracted_root,
            capture=True,
        )
        wheels = sorted(wheelhouse.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError(
                f"expected exactly one wheel from extracted archive, found {len(wheels)}"
            )
        with zipfile.ZipFile(wheels[0]) as wheel_archive:
            wheel_names = wheel_archive.namelist()
        if "dcnc_sim/__init__.py" not in wheel_names:
            raise RuntimeError("built wheel is missing dcnc_sim/__init__.py")
        placeholder_name = "TOP_LEVEL_LICENSE_REQUIRED.md"
        if any(PurePosixPath(name).name == placeholder_name for name in wheel_names):
            raise RuntimeError(
                "built wheel misclassifies the license-decision placeholder as license text"
            )
        if (strict or (extracted_root / "LICENSE").is_file()) and not any(
            ".dist-info/licenses/" in name
            and PurePosixPath(name).name == "LICENSE"
            for name in wheel_names
        ):
            raise RuntimeError("built wheel is missing its selected top-level LICENSE text")

        install_root = temp_root / "wheel-install"
        run_checked(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--no-index",
                "--target",
                str(install_root),
                str(wheels[0]),
            ],
            cwd=temp_root,
            capture=True,
        )
        run_checked(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    f"sys.path.insert(0, {str(install_root)!r}); "
                    "import dcnc_sim; "
                    "assert dcnc_sim.__file__ and "
                    f"str(dcnc_sim.__file__).startswith({str(install_root)!r})"
                ),
            ],
            cwd=temp_root,
            capture=True,
        )


def write_manifest_snapshot(root: Path, destination: Path, prefix: str) -> None:
    """Archive verified working files without staging or committing them."""
    inventory = json.loads((root / "manifests/files.json").read_text(encoding="utf-8"))
    entries = {entry["path"]: entry for entry in inventory["files"]}
    if len(entries) != len(inventory["files"]):
        raise RuntimeError("duplicate snapshot inventory path")
    names = sorted(set(entries) | {"SHA256SUMS.txt", "manifests/files.json"})
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative in names:
            member = zipfile.ZipInfo(prefix + relative, date_time=(2026, 10, 20, 0, 0, 0))
            validate_archive_member(member, prefix)
            path = root / relative
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError(f"unsafe snapshot source: {relative}")
            data = path.read_bytes()
            if relative in entries:
                entry = entries[relative]
                if len(data) != entry["bytes"] or sha256_bytes(data) != entry["sha256"]:
                    raise RuntimeError(f"snapshot source changed: {relative}")
            member.create_system = 3
            mode = 0o755 if path.suffix == ".sh" else 0o644
            member.external_attr = (stat.S_IFREG | mode) << 16
            member.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(member, data, compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="Allow open release gates and mark the archive as non-public candidate.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    parser.add_argument("--worktree-snapshot", action="store_true", help="Use the verified file manifest, including uncommitted files; never stage or commit.")
    args = parser.parse_args()

    dirty = run_checked(["git", "status", "--porcelain"], capture=True)
    if dirty and not args.worktree_snapshot:
        print("refusing to archive a dirty worktree:", file=sys.stderr)
        print(dirty, file=sys.stderr)
        return 2

    gate_suffix = [] if args.candidate else ["--strict"]
    claims = json.loads(
        (ROOT / "manifests" / "claims.json").read_text(encoding="utf-8")
    )
    paper_binding = claims.get("paper_project", claims["paper"])
    paper_filename = paper_binding["filename"]
    local_paper = ROOT.parent / paper_filename
    paper_source_check = {
        "status": "not-present",
        "filename": paper_filename,
        "expected_sha256": paper_binding["sha256"],
        "kind": paper_binding.get("kind", "pdf"),
        "compiled_pdf_verified": paper_binding.get("compiled_pdf_verified", False),
    }
    claim_command = [sys.executable, "scripts/verify_claims.py", *gate_suffix]
    if local_paper.is_file():
        paper_option = "--paper-project" if "paper_project" in claims else "--paper"
        claim_command.extend([paper_option, str(local_paper)])
        paper_source_check["status"] = "matched"
    try:
        run_checked(claim_command)
        run_checked(
            [sys.executable, "scripts/maintain_artifact.py", "verify", *gate_suffix]
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        if not args.candidate:
            print(
                "formal archive blocked; resolve every release gate or use "
                "--candidate for a clearly marked internal artifact",
                file=sys.stderr,
            )
        return 2

    version = artifact_version()
    commit = run_checked(["git", "rev-parse", "--short=12", "HEAD"], capture=True)
    label = f"dcnc-dag-reproducibility-{version}"
    if args.candidate:
        label += f"-candidate-{commit}"
    prefix = label + "/"
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"{label}.zip"
    checksum_path = archive_path.with_suffix(".zip.sha256")
    metadata_path = archive_path.with_suffix(".zip.json")
    for path in (archive_path, checksum_path, metadata_path):
        if path.exists():
            print(f"refusing to overwrite existing delivery file: {path}", file=sys.stderr)
            return 2

    temporary_path = output_dir / f".{label}.tmp.zip"
    rebuild_path = output_dir / f".{label}.rebuild.tmp.zip"
    for path in (temporary_path, rebuild_path):
        if path.exists():
            print(
                f"refusing to overwrite stale temporary file: {path}",
                file=sys.stderr,
            )
            return 2
    try:
        for destination in (temporary_path, rebuild_path):
            if args.worktree_snapshot:
                write_manifest_snapshot(ROOT, destination, prefix)
            else:
                run_checked(["git", "archive", "--format=zip", f"--prefix={prefix}", f"--output={destination}", "HEAD"])
        if sha256_file(temporary_path) != sha256_file(rebuild_path):
            raise RuntimeError(
                "two independent source archive builds were not byte-identical"
            )
        rebuild_path.unlink()
        archive_members, verified_files = validate_archive(
            temporary_path, prefix, require_license=not args.candidate
        )
        validate_extracted_archive(
            temporary_path, prefix, strict=not args.candidate
        )
        temporary_path.replace(archive_path)
    except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
        temporary_path.unlink(missing_ok=True)
        rebuild_path.unlink(missing_ok=True)
        print(f"archive build failed: {exc}", file=sys.stderr)
        return 1

    digest = sha256_file(archive_path)
    checksum_path.write_text(
        f"{digest}  {archive_path.name}\n", encoding="utf-8", newline="\n"
    )
    metadata = {
        "schema_version": 1,
        "built_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "artifact_version": version,
        "git_commit": None if args.worktree_snapshot else commit,
        "git_base_commit": commit,
        "source_kind": "manifest-worktree" if args.worktree_snapshot else "git-commit",
        "uncommitted_snapshot": bool(dirty) if args.worktree_snapshot else False,
        "file_manifest_sha256": sha256_file(ROOT / "manifests/files.json"),
        "candidate": args.candidate,
        "strict_release_gate": not args.candidate,
        "verification_runtime": verification_runtime(),
        "upstream_paper_check": paper_source_check,
        "archive": archive_path.name,
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": digest,
        "archive_members": archive_members,
        "manifested_files_verified": verified_files,
        "clean_room_checks": (
            ["upstream-paper-binding"]
            if paper_source_check["status"] == "matched"
            else []
        ) + [
            "claims",
            "integrity",
            "git-history-safety",
            "unit-tests",
            "compileall",
            "captured-verification-runtime",
            "source-archive-byte-rebuild",
            "wheel-build-install-import",
        ],
    }
    metadata_path.write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"built {'candidate' if args.candidate else 'formal'} archive: {archive_path}")
    print(f"SHA-256: {digest}")
    print(f"verified {verified_files} manifested files inside {archive_members} members")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
