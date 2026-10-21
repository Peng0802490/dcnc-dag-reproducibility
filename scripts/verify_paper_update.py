"""Verify the corrected Table 6 against raw runs and pinned manuscript excerpts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

if __package__:
    from .verify_table6_results import read_csv, require, verify_results
else:
    from verify_table6_results import read_csv, require, verify_results


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path("evidence/table6/paper_update")
EXCERPTS = {
    "table6.tex": ("TMC_Main.tex", 849, 871),
    "reductions.tex": ("TMC_Main.tex", 886, 886),
    "appendix_overhead.tex": ("TMC_Appendices.tex", 578, 578),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def project_files(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(name.casefold() for name in names)), "Duplicate project members")
        require(archive.testzip() is None, "Project ZIP CRC failure")
        return {name: archive.read(name) for name in names}


def capture_update(previous: Path, current: Path) -> dict[str, bytes]:
    before = project_files(previous)
    after = project_files(current)
    require(set(before) == set(after), "Unexpected added/deleted paper files")
    changed = {name for name in before if before[name] != after[name]}
    require(changed == {"TMC_Main.tex", "TMC_Appendices.tex"}, "Unexpected changed paper files")
    expected_lines = {"TMC_Main.tex": [863, 864, 865, 866, 867, 886], "TMC_Appendices.tex": [578]}
    for name in changed:
        old_lines = before[name].splitlines(keepends=True)
        new_lines = after[name].splitlines(keepends=True)
        require(len(old_lines) == len(new_lines), "Unexpected paper line count change")
        changed_lines = [index for index, pair in enumerate(zip(old_lines, new_lines), 1) if pair[0] != pair[1]]
        require(changed_lines == expected_lines[name], "Unexpected paper source edits")
    output = {}
    excerpts = []
    for filename, (source, first, last) in EXCERPTS.items():
        data = b"".join(after[source].splitlines(keepends=True)[first - 1:last])
        output[filename] = data
        excerpts.append({"path": filename, "source_file": source, "first_line": first, "last_line": last, "sha256": digest(data)})
    audit = {
        "schema_version": 1,
        "verification_scope": "latex-source; updated compiled PDF not supplied or checked",
        "previous_project": {"filename": previous.name, "sha256": digest(previous.read_bytes())},
        "project": {"filename": current.name, "sha256": digest(current.read_bytes())},
        "members": [{"path": name, "before_sha256": digest(before[name]), "after_sha256": digest(after[name])} for name in sorted(after)],
        "changed_source_lines": expected_lines,
        "excerpts": excerpts,
    }
    output["source_audit.json"] = (json.dumps(audit, indent=2) + "\n").encode("utf-8")
    return output


def verify_update(root: Path = ROOT, project_path: Path | None = None) -> dict:
    manifest = json.loads((root / "manifests/claims.json").read_text(encoding="utf-8"))
    binding = manifest["paper_project"]
    claim = manifest["claims"]["table6"]
    audit = json.loads((root / EVIDENCE / "source_audit.json").read_text(encoding="utf-8"))
    require(audit["project"] == {key: binding[key] for key in ("filename", "sha256")}, "Paper project identity")
    require(binding["kind"] == "latex-project" and binding["compiled_pdf_verified"] is False, "Paper verification scope")
    require(claim["paper_source_sha256"] == binding["sha256"], "Table 6 source identity")
    require(claim["paper_update_evidence"] == EVIDENCE.as_posix(), "Table 6 source evidence path")
    decision = manifest["publication_decision"]
    require(decision["paper_alignment"] == "verified-updated-latex-project", "Paper alignment decision")
    require(decision["release_preparation_authorized"] is True, "Release preparation decision")
    require(decision["manuscript_method_expansion"] == "declined-by-owner", "Method scope decision")
    members = {entry["path"]: entry for entry in audit["members"]}
    require(len(members) == len(audit["members"]) == 18, "Paper project member count")
    changed = {name for name, entry in members.items() if entry["before_sha256"] != entry["after_sha256"]}
    require(changed == {"TMC_Main.tex", "TMC_Appendices.tex"}, "Paper project change scope")
    require(audit["changed_source_lines"] == {"TMC_Main.tex": [863, 864, 865, 866, 867, 886], "TMC_Appendices.tex": [578]}, "Paper changed-line scope")
    external = None
    if project_path is not None:
        require(digest(project_path.read_bytes()) == binding["sha256"], "External paper project hash")
        external = project_files(project_path)
        require(set(external) == set(members), "External paper project members")
        for name, data in external.items():
            require(digest(data) == members[name]["after_sha256"], "External paper member hash")
    require(len(audit["excerpts"]) == len(EXCERPTS), "Paper excerpt count")
    texts = {}
    for entry in audit["excerpts"]:
        filename = entry["path"]
        require(filename in EXCERPTS and filename not in texts, "Unexpected paper excerpt")
        source, first, last = EXCERPTS[filename]
        require((entry["source_file"], entry["first_line"], entry["last_line"]) == (source, first, last), "Paper excerpt source lines")
        data = (root / EVIDENCE / filename).read_bytes()
        require(digest(data) == entry["sha256"], "Paper excerpt hash")
        if external is not None:
            require(data == b"".join(external[source].splitlines(keepends=True)[first - 1:last]), "External paper excerpt mismatch")
        texts[filename] = data.decode("utf-8")
    result = verify_results(root, claim)
    summaries = {(row["case"], int(row["fixed_k"])): row for row in read_csv(root / claim["summary_evidence"])}
    frames = set()
    for line in texts["table6.tex"].splitlines():
        if not re.match(r"^\s*\d+\s*&", line):
            continue
        cells = [cell.strip().rstrip("\\").strip() for cell in line.split("&")]
        require(len(cells) == 7, "Paper Table 6 column count")
        frame = int(cells[0])
        require(frame in {1, 4, 16, 64, 256} and frame not in frames, "Paper Table 6 frame")
        frames.add(frame)
        for topology, case, offset in (("Milan", "driving_milan", 1), ("Random", "driving_random", 4)):
            summary = summaries[(case, frame)]
            seconds = float(summary["mean_dynvmp_wall_time_sec"]) / claim["slots"]
            printed = f"{seconds:.4f}" if seconds < 0.1 else f"{seconds:.3f}"
            require(cells[offset] == f"{manifest['claims']['frame_length']['thresholds'][topology][str(frame)]:.2f}", "Paper supported rate")
            require(cells[offset + 1] == f"{float(summary['mean_dynvmp_calls']):.1f}", "Paper mapping calls")
            require(cells[offset + 2] == printed, "Paper mapping timing")
    require(len(frames) == 5, "Paper Table 6 row count")
    expected = []
    for metric in ("mean_dynvmp_calls", "mean_dynvmp_wall_time_sec"):
        for case in ("driving_milan", "driving_random"):
            percent = 100 * (1 - float(summaries[(case, 256)][metric]) / float(summaries[(case, 1)][metric]))
            expected.append(f"{percent:.1f}")
    require(re.findall(r"(\d+\.\d+)\\%", texts["reductions.tex"]) == expected, "Paper reduction percentages")
    require("three seeds per rate (15 runs per topology and frame length; 150 runs total)" in texts["appendix_overhead.tex"], "Paper run counts")
    return {**result, "verification_scope": "latex-source", "compiled_pdf_verified": False, "unchanged_project_members": len(members) - len(changed)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path)
    parser.add_argument("--previous-project", type=Path)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    if args.capture:
        if args.project is None or args.previous_project is None:
            parser.error("capture requires both project archives")
        output = ROOT / EVIDENCE
        generated = capture_update(args.previous_project, args.project)
        for name, data in generated.items():
            path = output / name
            if path.exists():
                require(path.read_bytes() == data, "Refusing to overwrite different paper evidence")
        output.mkdir(parents=True, exist_ok=True)
        for name, data in generated.items():
            (output / name).write_bytes(data)
    print(json.dumps(verify_update(ROOT, args.project), indent=2))


if __name__ == "__main__":
    main()
