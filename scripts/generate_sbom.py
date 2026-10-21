#!/usr/bin/env python3
"""Generate the deterministic SPDX 2.3 software bill of materials."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATED = "2026-09-27T00:00:00Z"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def spdx_id(label: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9.-]+", "-", label).strip("-")
    return f"SPDXRef-Package-{normalized}"


def project_metadata(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_project = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if not in_project:
            continue
        match = re.fullmatch(r'(name|version|license)\s*=\s*"([^"]+)"', line)
        if match:
            values[match.group(1)] = match.group(2)
    if not values.get("name") or not values.get("version"):
        raise ValueError("pyproject.toml lacks project name or version")
    return values


def exact_constraints(text: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^,;\s]+)", line)
        if not match:
            raise ValueError(f"non-exact constraint: {line}")
        name = normalize_name(match.group(1))
        if name in versions:
            raise ValueError(f"duplicate constraint: {name}")
        versions[name] = match.group(2)
    if not versions:
        raise ValueError("constraints-main.txt is empty")
    return versions


def package(
    *,
    name: str,
    identifier: str,
    version: str | None = None,
    download: str = "NOASSERTION",
    declared_license: str = "NOASSERTION",
    concluded_license: str = "NOASSERTION",
    purpose: str = "LIBRARY",
    comment: str | None = None,
    purl: str | None = None,
) -> dict:
    item = {
        "SPDXID": identifier,
        "name": name,
        "downloadLocation": download,
        "filesAnalyzed": False,
        "licenseConcluded": concluded_license,
        "licenseDeclared": declared_license,
        "copyrightText": "NOASSERTION",
        "primaryPackagePurpose": purpose,
    }
    if version:
        item["versionInfo"] = version
    if comment:
        item["comment"] = comment
    if purl:
        item["externalRefs"] = [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl,
            }
        ]
    return item


def build_sbom(repo_root: Path = ROOT) -> dict:
    pyproject_path = repo_root / "pyproject.toml"
    constraints_path = repo_root / "constraints-main.txt"
    third_party_path = repo_root / "manifests" / "third_party.json"
    metadata = project_metadata(pyproject_path.read_text(encoding="utf-8"))
    constraints = exact_constraints(constraints_path.read_text(encoding="utf-8"))
    third_party = json.loads(third_party_path.read_text(encoding="utf-8"))

    identity_material = "|".join(
        [
            sha256(pyproject_path),
            sha256(constraints_path),
            sha256(third_party_path),
        ]
    ).encode("ascii")
    identity = hashlib.sha256(identity_material).hexdigest()[:20]
    root_id = spdx_id(metadata["name"])
    license_declared = metadata.get("license", "NOASSERTION")
    packages = [
        package(
            name=metadata["name"],
            identifier=root_id,
            version=metadata["version"],
            declared_license=license_declared,
            concluded_license=license_declared,
            purpose="APPLICATION",
            comment=(
                "First-party reproducibility artifact. NOASSERTION is deliberate "
                "while the top-level license release gate remains open."
            ),
            purl=f"pkg:pypi/{normalize_name(metadata['name'])}@{metadata['version']}",
        )
    ]
    relationships = []

    for name, version in sorted(constraints.items()):
        identifier = spdx_id(f"pypi-{name}")
        packages.append(
            package(
                name=name,
                identifier=identifier,
                version=version,
                purl=f"pkg:pypi/{name}@{version}",
                comment="Exact package in the pinned Python 3 verification environment.",
            )
        )
        relationships.append(
            {
                "spdxElementId": root_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": identifier,
            }
        )

    for entry in sorted(
        third_party["license_files"], key=lambda item: item["component"]
    ):
        name = entry["component"]
        identifier = spdx_id(f"vendored-{name}")
        packages.append(
            package(
                name=name,
                identifier=identifier,
                declared_license=entry["spdx"],
                concluded_license=entry["spdx"],
                comment=(
                    f"Vendored source snapshot at {entry['path']}; "
                    f"license SHA-256 {entry['sha256']}."
                ),
            )
        )
        relationships.append(
            {
                "spdxElementId": root_id,
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": identifier,
            }
        )

    sources = third_party["data_sources"]
    data_specs = [
        (
            "internet-topology-zoo",
            "Internet Topology Zoo",
            None,
            "NOASSERTION",
            sources["internet_topology_zoo"]["license"],
            "CONTAINS",
            sources["internet_topology_zoo"]["classification"],
        ),
        (
            "flocklab",
            sources["flocklab"]["source_title"],
            sources["flocklab"]["source_version"],
            sources["flocklab"]["source_record"],
            sources["flocklab"]["license"],
            "CONTAINS",
            sources["flocklab"]["classification"],
        ),
        (
            "wfcommons-sra-search",
            "WfCommons WfInstances SRA-Search source",
            None,
            sources["wfcommons_sra_search"]["source_repository"],
            sources["wfcommons_sra_search"]["source_repository_license"],
            "GENERATED_FROM",
            sources["wfcommons_sra_search"]["classification"]
            + "; raw source is not redistributed",
        ),
        (
            "pegasus-sipht",
            "Pegasus Workflow Gallery SIPHT source",
            None,
            sources["pegasus_sipht"]["source_page"],
            "NOASSERTION",
            "GENERATED_FROM",
            sources["pegasus_sipht"]["classification"]
            + "; raw source is not redistributed and the archived run has no separate license label",
        ),
    ]
    for key, name, version, download, license_id, relation, comment in data_specs:
        identifier = spdx_id(f"data-{key}")
        packages.append(
            package(
                name=name,
                identifier=identifier,
                version=version,
                download=download,
                declared_license=license_id,
                concluded_license=license_id,
                purpose="OTHER",
                comment=comment,
            )
        )
        relationships.append(
            {
                "spdxElementId": root_id,
                "relationshipType": relation,
                "relatedSpdxElement": identifier,
            }
        )

    relationships.sort(
        key=lambda item: (
            item["spdxElementId"],
            item["relationshipType"],
            item["relatedSpdxElement"],
        )
    )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{metadata['name']}-{metadata['version']}",
        "documentNamespace": (
            "https://spdx.org/spdxdocs/"
            f"dcnc-dag-reproducibility-{metadata['version']}-{identity}"
        ),
        "creationInfo": {
            "created": CREATED,
            "creators": ["Tool: scripts/generate_sbom.py"],
            "comment": (
                "Deterministically generated from pyproject.toml, "
                "constraints-main.txt, and manifests/third_party.json."
            ),
        },
        "documentDescribes": [root_id],
        "packages": packages,
        "relationships": relationships,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "SBOM.spdx.json")
    args = parser.parse_args()
    sbom = build_sbom()
    rendered = json.dumps(sbom, indent=2, sort_keys=True) + "\n"
    output = args.output if args.output.is_absolute() else ROOT / args.output
    if args.check:
        try:
            current = output.read_text(encoding="utf-8")
        except OSError:
            print(f"SBOM missing: {output}")
            return 1
        if current != rendered:
            print(f"SBOM is stale: {output}")
            return 1
        print(f"SBOM is current: {output}")
        return 0
    output.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {len(sbom['packages'])} SPDX packages to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
