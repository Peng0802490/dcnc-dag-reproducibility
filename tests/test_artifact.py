from __future__ import annotations

import json
import importlib.util
import csv
import contextlib
import hashlib
import io
import stat
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]


class ArtifactTests(unittest.TestCase):
    def test_upstream_state_detects_paper_change_without_writing(self) -> None:
        from scripts.check_upstream_state import inspect_upstream_state

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            artifact = root / "artifact"
            paper_repo = root / "paper"
            (artifact / "manifests").mkdir(parents=True)
            paper_repo.mkdir()
            paper = paper_repo / "paper.pdf"
            paper.write_bytes(b"pinned paper")
            expected_hash = hashlib.sha256(paper.read_bytes()).hexdigest().upper()
            claims = {
                "artifact_version": "1.0.0",
                "paper": {"filename": paper.name, "sha256": expected_hash},
                "source_provenance": {
                    "paper_repo_local_head": "1" * 40,
                    "paper_repo_origin_master": "2" * 40,
                },
            }
            (artifact / "manifests" / "claims.json").write_text(
                json.dumps(claims), encoding="utf-8", newline="\n"
            )
            before = paper.read_bytes()

            matched = inspect_upstream_state(artifact, paper, paper_repo)

            self.assertEqual(matched["paper"]["status"], "matched")
            self.assertFalse(matched["update_required"])
            self.assertEqual(matched["missing_inputs"], ["paper-repository"])
            self.assertEqual(paper.read_bytes(), before)

            paper.write_bytes(b"new paper")
            changed = inspect_upstream_state(artifact, paper, paper_repo)
            self.assertEqual(changed["paper"]["status"], "changed")
            self.assertTrue(changed["update_required"])
            self.assertEqual(changed["updates"], ["paper-pdf"])

    def test_archive_path_portability_gate(self) -> None:
        from scripts.build_release_archive import (
            validate_archive,
            validate_archive_member,
        )

        def rejected(entries: list[zipfile.ZipInfo | str], pattern: str) -> None:
            with tempfile.TemporaryDirectory() as temp_name:
                archive_path = Path(temp_name) / "test.zip"
                with zipfile.ZipFile(archive_path, "w") as archive:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", UserWarning)
                        for entry in entries:
                            archive.writestr(entry, b"test")
                with self.assertRaisesRegex(RuntimeError, pattern):
                    validate_archive(
                        archive_path, "package/", require_license=False
                    )

        rejected(
            ["package/repeated", "package/repeated"],
            "duplicate member names",
        )
        rejected(
            ["package/Result.csv", "package/result.csv"],
            "case-colliding members",
        )
        backslash = zipfile.ZipInfo("placeholder")
        backslash.filename = r"package\escape.txt"
        with self.assertRaisesRegex(RuntimeError, "backslash"):
            validate_archive_member(backslash, "package/")
        rejected(["package/AUX.txt"], "Windows-reserved name")
        rejected(["package/trailing-dot."], "not Windows-portable")
        rejected(
            ["package/evidence/__pycache__/stale.cpython-311.pyc"],
            "generated build/cache material",
        )
        rejected(
            ["package/src/dcnc_sim.egg-info/PKG-INFO"],
            "generated build/cache material",
        )
        symlink = zipfile.ZipInfo("package/link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        rejected([symlink], "symbolic link")

    def test_archive_forbidden_member_reports_actual_path(self) -> None:
        from scripts.build_release_archive import validate_archive

        with tempfile.TemporaryDirectory() as temp_name:
            archive_path = Path(temp_name) / "test.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("package/README.md", b"test")
                archive.writestr("package/results/leak.csv", b"test")
            with self.assertRaisesRegex(
                RuntimeError, r"package/results/leak\.csv"
            ):
                validate_archive(
                    archive_path, "package/", require_license=False
                )

    def test_archive_verification_runtime_contract(self) -> None:
        from scripts.build_release_archive import verification_runtime

        runtime = verification_runtime()
        self.assertEqual(
            set(runtime),
            {
                "python",
                "implementation",
                "system",
                "system_release",
                "machine",
                "pip",
                "setuptools",
                "wheel",
            },
        )
        self.assertRegex(runtime["python"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(runtime["implementation"], "CPython")
        self.assertTrue(all(runtime[key] for key in runtime))

    def test_artifact_version_contract(self) -> None:
        from scripts.maintain_artifact import artifact_version_issues

        self.assertEqual(artifact_version_issues(ROOT), [])
        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name)
            (repo / "manifests").mkdir()
            (repo / "docs").mkdir()
            (repo / "pyproject.toml").write_text(
                '[project]\nversion = "1.2.3"\n', encoding="utf-8", newline="\n"
            )
            (repo / "manifests" / "claims.json").write_text(
                '{"artifact_version": "1.2.2"}\n',
                encoding="utf-8",
                newline="\n",
            )
            (repo / "CHANGELOG.md").write_text(
                "# Changelog\n\n## 1.2.1 - test\n",
                encoding="utf-8",
                newline="\n",
            )
            (repo / "CITATION.cff").write_text(
                'cff-version: "1.2.0"\nversion: "1.2.0"\n',
                encoding="utf-8",
                newline="\n",
            )
            (repo / "docs" / "VALIDATION.md").write_text(
                "Validation for artifact version `1.2.0`.\n",
                encoding="utf-8",
                newline="\n",
            )
            issues = artifact_version_issues(repo)
            self.assertEqual(len(issues), 4)
            self.assertTrue(all("expected '1.2.3'" in issue for issue in issues))

    def test_citation_metadata_contract(self) -> None:
        import yaml

        citation = yaml.safe_load(
            (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        )
        claims = json.loads(
            (ROOT / "manifests" / "claims.json").read_text(encoding="utf-8")
        )
        expected_authors = [
            {
                "given-names": author["given_names"],
                "family-names": author["family_names"],
            }
            for author in claims["paper"]["authors"]
        ]
        self.assertEqual(citation["cff-version"], "1.2.0")
        self.assertEqual(citation["type"], "software")
        self.assertEqual(citation["version"], claims["artifact_version"])
        self.assertEqual(citation["authors"], expected_authors)
        preferred = citation["preferred-citation"]
        self.assertEqual(preferred["type"], "article")
        self.assertEqual(preferred["title"], claims["paper"]["title"])
        self.assertEqual(preferred["authors"], expected_authors)

    def test_sbom_contract(self) -> None:
        from scripts.maintain_artifact import sbom_issues

        self.assertEqual(sbom_issues(ROOT), [])
        sbom = json.loads((ROOT / "SBOM.spdx.json").read_text(encoding="utf-8"))
        packages = sbom["packages"]
        identifiers = [item["SPDXID"] for item in packages]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        root_id = sbom["documentDescribes"][0]
        root_package = next(item for item in packages if item["SPDXID"] == root_id)
        from scripts.generate_sbom import project_metadata
        project = project_metadata((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(root_package["licenseDeclared"], project.get("license", "NOASSERTION"))
        pinned = {
            line.split("==", 1)[0].lower(): line.split("==", 1)[1]
            for line in (ROOT / "constraints-main.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        }
        purls = {
            reference["referenceLocator"]
            for item in packages
            for reference in item.get("externalRefs", [])
        }
        for name, version in pinned.items():
            self.assertIn(f"pkg:pypi/{name}@{version}", purls)

    def test_delivery_metadata_contract(self) -> None:
        from scripts.build_release_archive import REQUIRED_ARCHIVE_FILES

        expected = {
            "CHANGELOG.md",
            "CITATION.cff",
            "CONTRIBUTING.md",
            "README.md",
            "RELEASE_NOTES.md",
            "docs/GITHUB_RELEASE.md",
            "REPRODUCIBILITY_STATUS.md",
            "SBOM.spdx.json",
            "SECURITY.md",
            "THIRD_PARTY.md",
            "scripts/check_upstream_state.py",
            "scripts/table6_progress_probe.py",
            "scripts/update_table6_progress.py",
        }
        self.assertTrue(expected.issubset(REQUIRED_ARCHIVE_FILES))
        for relative in expected:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_ci_workflow_contract(self) -> None:
        import yaml

        workflow_path = ROOT / ".github" / "workflows" / "artifact-integrity.yml"
        workflow_text = workflow_path.read_text(encoding="utf-8")
        workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
        self.assertEqual(workflow["permissions"]["contents"], "read")
        self.assertEqual(
            set(workflow["on"]), {"push", "pull_request", "workflow_dispatch"}
        )

        steps = workflow["jobs"]["verify"]["steps"]
        checkout = next(
            step for step in steps if step.get("uses") == "actions/checkout@v7"
        )
        self.assertEqual(checkout["with"]["fetch-depth"], "0")
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        setup = next(
            step for step in steps if step.get("uses") == "actions/setup-python@v7"
        )
        self.assertEqual(setup["with"]["python-version"], "3.10.20")
        self.assertEqual(
            setup["with"]["cache-dependency-path"], "constraints-main.txt"
        )

        commands = "\n".join(step.get("run", "") for step in steps)
        for required in (
            "--constraint constraints-main.txt --editable .",
            "python -m pip check",
            "scripts/generate_sbom.py --check",
            "scripts/maintain_artifact.py verify",
            "scripts/verify_claims.py",
            "unittest discover -s tests -v",
            "compileall -q src scripts tools tests evidence inputs",
            "bash -n",
            "scripts/build_release_archive.py --candidate",
        ):
            self.assertIn(required, commands)

        formal_step = next(
            step for step in steps
            if step.get("name") == "Require a formal archive for version tags"
        )
        self.assertEqual(formal_step["if"], "startsWith(github.ref, 'refs/tags/v')")
        for command in (
            "python scripts/verify_claims.py --strict",
            "python scripts/maintain_artifact.py verify --strict",
            "python scripts/build_release_archive.py",
        ):
            self.assertIn(command, formal_step["run"].splitlines())
        self.assertNotIn("--candidate", formal_step["run"])

    def test_owner_license_and_release_preparation(self) -> None:
        from scripts.generate_sbom import project_metadata
        from scripts.maintain_artifact import license_selection_issues

        claims = json.loads((ROOT / "manifests/claims.json").read_text(encoding="utf-8"))
        project = project_metadata((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        decision = claims["publication_decision"]
        self.assertEqual(project["license"], decision["first_party_license"])
        self.assertEqual(license_selection_issues(ROOT), [])
        self.assertTrue((ROOT / "LICENSE").read_text(encoding="utf-8").startswith("MIT License\n"))
        self.assertNotIn("top-level-license-not-selected", claims["open_gates"])
        self.assertEqual(decision["paper_alignment"], "verified-updated-latex-project")
        self.assertTrue(claims["release_ready"])
        self.assertTrue(decision["release_preparation_authorized"])
        self.assertTrue(decision["public_release_authorized"])
        self.assertEqual(claims["open_gates"], [])
        self.assertFalse(claims["paper_project"]["compiled_pdf_verified"])

    def test_corrected_paper_source_and_tampering(self) -> None:
        from scripts.verify_paper_update import verify_update
        from unittest.mock import patch

        result = verify_update(ROOT)
        self.assertEqual(result["paper_timing_mismatches"], 0)
        self.assertEqual(result["validated_runs"], 150)
        self.assertEqual(result["unchanged_project_members"], 16)
        original_read = Path.read_bytes

        def tampered_read(path: Path) -> bytes:
            content = original_read(path)
            return content.replace(b"2.825", b"1.910") if path.name == "table6.tex" else content

        with patch.object(Path, "read_bytes", tampered_read):
            with self.assertRaisesRegex(ValueError, "Paper excerpt hash"):
                verify_update(ROOT)

    def test_old_table6_numbers_cannot_satisfy_exact_source_status(self) -> None:
        from scripts.verify_table6_results import verify_results

        claim = json.loads((ROOT / "manifests/claims.json").read_text(encoding="utf-8"))["claims"]["table6"]
        claim["paper_seconds_per_slot"] = claim["historical_pdf_seconds_per_slot"]
        with self.assertRaisesRegex(ValueError, "timing mismatch classification"):
            verify_results(ROOT, claim)

    def test_external_paper_project_must_match(self) -> None:
        from scripts.verify_paper_update import verify_update

        with tempfile.TemporaryDirectory() as temporary:
            changed = Path(temporary) / "changed.zip"
            changed.write_bytes(b"changed project")
            with self.assertRaisesRegex(ValueError, "External paper project hash"):
                verify_update(ROOT, changed)

    def test_environment_contract_gate(self) -> None:
        from scripts.maintain_artifact import environment_contract_issues

        self.assertEqual(environment_contract_issues(ROOT), [])
        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name)
            (repo / "requirements.txt").write_text(
                "numpy>=1.24\n", encoding="utf-8", newline="\n"
            )
            (repo / "constraints-main.txt").write_text(
                "numpy==2.2.6\n", encoding="utf-8", newline="\n"
            )
            (repo / "pyproject.toml").write_text(
                '[project]\ndependencies = ["numpy>=1.24"]\n',
                encoding="utf-8",
                newline="\n",
            )
            (repo / "environment_dcnc_dag.yml").write_text(
                "dependencies:\n  - python=3.10.20=build\n  - pip:\n"
                "      - numpy==2.2.6\n",
                encoding="utf-8",
                newline="\n",
            )
            (repo / "environment_dynvmp_py2.yml").write_text(
                "dependencies:\n  - python=2.7.15=build\n  - pip:\n"
                "      - gurobipy==9.1.2\n",
                encoding="utf-8",
                newline="\n",
            )
            fingerprint = repo / "evidence" / "table6"
            fingerprint.mkdir(parents=True)
            (fingerprint / "runtime_fingerprint.json").write_text(
                json.dumps(
                    {
                        "software": {
                            "main_python": "3.10.20",
                            "dynvmp_python": "2.7.15",
                            "dynvmp_gurobipy": "9.1.2",
                        }
                    }
                ),
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(environment_contract_issues(repo), [])

            (repo / "constraints-main.txt").write_text(
                "numpy>=2.2.6\n", encoding="utf-8", newline="\n"
            )
            issues = environment_contract_issues(repo)
            self.assertIn(
                "main pip constraints contain non-exact entries: numpy", issues
            )
            self.assertIn(
                "constraints-main.txt does not exactly match main environment pip pins",
                issues,
            )
            (repo / "constraints-main.txt").write_text(
                "numpy==2.2.6\n", encoding="utf-8", newline="\n"
            )

            (repo / "requirements.txt").write_text(
                "numpy>=1.24\npandas>=2.0\n", encoding="utf-8", newline="\n"
            )
            issues = environment_contract_issues(repo)
            self.assertIn(
                "requirements.txt and pyproject.toml dependency specifications disagree",
                issues,
            )
            self.assertTrue(
                any("pandas" in issue for issue in issues),
                issues,
            )

            (repo / "requirements.txt").write_text(
                "numpy>=99\n", encoding="utf-8", newline="\n"
            )
            (repo / "pyproject.toml").write_text(
                '[project]\ndependencies = ["numpy>=99"]\n',
                encoding="utf-8",
                newline="\n",
            )
            issues = environment_contract_issues(repo)
            self.assertTrue(
                any(
                    "numpy==2.2.6 does not satisfy numpy>=99" in issue
                    for issue in issues
                ),
                issues,
            )

    def test_third_party_notice_gate(self) -> None:
        from scripts.maintain_artifact import third_party_notice_issues

        self.assertEqual(third_party_notice_issues(ROOT), [])

    def test_license_selection_gate(self) -> None:
        from scripts.maintain_artifact import license_selection_issues

        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name)
            (repo / "pyproject.toml").write_text(
                '[project]\nname = "example"\n', encoding="utf-8", newline="\n"
            )
            issues = license_selection_issues(repo)
            self.assertIn("top-level LICENSE missing", issues)
            self.assertIn(
                "pyproject.toml [project] license metadata missing", issues
            )

            (repo / "LICENSE").write_text(
                "placeholder\n", encoding="utf-8", newline="\n"
            )
            self.assertIn(
                "top-level LICENSE is too short to contain complete license text",
                license_selection_issues(repo),
            )

            (repo / "LICENSE").write_text(
                "complete test-only license text\n" * 8,
                encoding="utf-8",
                newline="\n",
            )
            (repo / "pyproject.toml").write_text(
                '[project]\nname = "example"\nlicense = "MIT"\n',
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(license_selection_issues(repo), [])

    def test_external_paper_binding_gate(self) -> None:
        from scripts.verify_claims import verify_external_paper

        with tempfile.TemporaryDirectory() as temp_name:
            paper = Path(temp_name) / "paper.pdf"
            paper.write_bytes(b"test-only paper bytes")
            digest = hashlib.sha256(paper.read_bytes()).hexdigest()
            matching_failures: list[str] = []
            with contextlib.redirect_stdout(io.StringIO()):
                verify_external_paper(
                    {"paper": {"sha256": digest}}, paper, matching_failures
                )
            self.assertEqual(matching_failures, [])

            mismatching_failures: list[str] = []
            with contextlib.redirect_stdout(io.StringIO()):
                verify_external_paper(
                    {"paper": {"sha256": "0" * 64}},
                    paper,
                    mismatching_failures,
                )
            self.assertEqual(
                mismatching_failures, ["metadata/upstream-paper-sha256"]
            )

    def test_sensitive_filename_gate(self) -> None:
        from scripts.maintain_artifact import sensitive_filename

        blocked = [
            ".env",
            ".env.local",
            "gurobi.lic",
            "id_rsa",
            "credentials.json",
            "client_secret_project.json",
            "service-account-prod.json",
            "private.pem",
        ]
        allowed = [
            "environment_dcnc_dag.yml",
            "TOP_LEVEL_LICENSE_REQUIRED.md",
            "public_key.pub",
            "credentials_helper.py",
        ]
        for name in blocked:
            self.assertTrue(sensitive_filename(Path(name)), name)
        for name in allowed:
            self.assertFalse(sensitive_filename(Path(name)), name)

    def test_git_history_sensitive_data_gate(self) -> None:
        from scripts.maintain_artifact import git_history_safety_findings

        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name)

            def git(*args: str) -> None:
                completed = subprocess.run(
                    ["git", *args],
                    cwd=repo,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout)

            git("init", "--quiet")
            git("config", "user.name", "Artifact Test")
            git("config", "user.email", "artifact-test@example.invalid")
            (repo / ".env").write_text(
                "TEST_ONLY=true\n", encoding="utf-8", newline="\n"
            )
            test_secret = "not-a-real-password"
            (repo / "notes.txt").write_text(
                'password="' + test_secret + '"\n',
                encoding="utf-8",
                newline="\n",
            )
            git("add", ".env", "notes.txt")
            git("commit", "--quiet", "-m", "add then remove sensitive fixtures")
            (repo / ".env").unlink()
            (repo / "notes.txt").unlink()
            git("add", "-u")
            git("commit", "--quiet", "-m", "remove sensitive fixtures")

            findings = git_history_safety_findings(repo)
            rendered = "\n".join(findings)
            self.assertIn("sensitive filename in Git history: .env", rendered)
            self.assertIn(
                "possible credential assignment in Git history: notes.txt",
                rendered,
            )
            self.assertNotIn(test_secret, rendered)

    def test_package_import(self) -> None:
        if importlib.util.find_spec("networkx") is None:
            self.skipTest("optional simulator dependencies are not installed")
        sys.path.insert(0, str(ROOT / "src"))
        import dcnc_sim  # noqa: F401

    def test_reproduction_keeps_fifo_evidence_immutable(self) -> None:
        from scripts.reproduce_paper_results import prepare_fifo_workspace

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            evidence_root = root / "evidence"
            results_root = root / "results"
            source_data = evidence_root / "fifo" / "data"
            source_scripts = evidence_root / "fifo" / "scripts"
            source_figures = evidence_root / "fifo" / "figures"
            source_data.mkdir(parents=True)
            source_scripts.mkdir()
            source_figures.mkdir()
            (source_data / "rows.csv").write_text(
                "value\n1\n", encoding="utf-8", newline="\n"
            )
            (source_scripts / "plot_backlog_results.py").write_text(
                "print('plot')\n", encoding="utf-8", newline="\n"
            )
            (source_figures / "pinned.pdf").write_bytes(b"pinned-evidence")
            before = {
                path.relative_to(evidence_root).as_posix(): path.read_bytes()
                for path in evidence_root.rglob("*")
                if path.is_file()
            }

            copied_script = prepare_fifo_workspace(evidence_root, results_root)

            after = {
                path.relative_to(evidence_root).as_posix(): path.read_bytes()
                for path in evidence_root.rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            self.assertEqual(
                copied_script,
                results_root / "fifo" / "scripts" / "plot_backlog_results.py",
            )
            self.assertEqual(
                copied_script.read_text(encoding="utf-8"), "print('plot')\n"
            )
            self.assertEqual(
                (results_root / "fifo" / "data" / "rows.csv").read_text(
                    encoding="utf-8"
                ),
                "value\n1\n",
            )
            self.assertFalse((results_root / "fifo" / "figures").exists())

    def test_k100k_contract(self) -> None:
        records = [
            json.loads(line)
            for line in (ROOT / "evidence" / "main_sweeps" / "k100k.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertEqual(len(records), 480)
        self.assertTrue(all(row["status"] == "ok" for row in records))
        self.assertEqual({row["seed"] for row in records}, {1, 2, 3})
        self.assertEqual({row["slots"] for row in records}, {100000})

    def test_declared_claims(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_claims.py")],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout)

    def test_table6_progress_contract(self) -> None:
        claims = json.loads(
            (ROOT / "manifests" / "claims.json").read_text(encoding="utf-8")
        )["claims"]["table6"]
        progress = json.loads(
            (ROOT / claims["progress_evidence"]).read_text(encoding="utf-8")
        )
        observed = sum(
            int(progress[name])
            for name in ("completed", "running", "queued", "failed")
        )
        self.assertEqual(observed, claims["expected_jobs"])
        self.assertEqual(progress["failed"], 0)
        self.assertTrue(progress["final"])
        self.assertEqual(progress["completed"], claims["expected_jobs"])

    def test_table6_imported_results_reject_tampering(self) -> None:
        from scripts.verify_table6_results import verify_results
        from unittest.mock import patch

        claim = json.loads(
            (ROOT / "manifests/claims.json").read_text(encoding="utf-8")
        )["claims"]["table6"]
        self.assertEqual(verify_results(ROOT, claim)["validated_runs"], 150)
        original_read = Path.read_bytes

        def tampered_read(path: Path) -> bytes:
            content = original_read(path)
            if path.name == "edge_experiments_all_results.csv":
                return content + b"\n"
            return content

        with patch.object(Path, "read_bytes", tampered_read):
            with self.assertRaisesRegex(ValueError, "raw hash"):
                verify_results(ROOT, claim)

        changed = json.loads(json.dumps(claim))
        changed["observed_seconds_per_slot"]["driving_milan"]["1"] = 1.91
        with self.assertRaisesRegex(ValueError, "declared observed timing"):
            verify_results(ROOT, changed)

    def test_moe_latest_figure_records(self) -> None:
        from scripts.verify_moe_censored import verify_results
        from unittest.mock import patch

        self.assertEqual(verify_results(ROOT), {"runs": 321, "pending_records": 179264, "aggregate_points": 107, "displayed_points": 106})
        original_read = Path.read_bytes

        def tampered_read(path: Path) -> bytes:
            data = original_read(path)
            return data + b"bad" if path.name.endswith(".csv.gz") else data

        with patch.object(Path, "read_bytes", tampered_read):
            with self.assertRaisesRegex(ValueError, "MoE raw"):
                verify_results(ROOT)
        bad_request = "request_id,arrival_slot,cutoff_T,delay_lower_bound_slots\nrequest,5,100000,2\n"
        with patch("gzip.open", return_value=io.StringIO(bad_request)):
            with self.assertRaisesRegex(ValueError, "MoE pending age"):
                verify_results(ROOT)

    def test_moe_current_claim_rejects_old_threshold(self) -> None:
        from scripts.verify_claims import verify_moe

        claims = json.loads((ROOT / "manifests/claims.json").read_text(encoding="utf-8"))["claims"]
        claims["moe"]["paper"]["mixtral"]["FlexMoE-style"] = 0.52
        failures = []
        with contextlib.redirect_stdout(io.StringIO()):
            verify_moe(claims, failures)
        self.assertTrue(any("current-paper/mixtral/FlexMoE-style" in failure for failure in failures))

    def test_table6_replacement_is_generated_from_raw_results(self) -> None:
        from scripts.generate_table6_replacement import replacement_files

        for name, expected in replacement_files(ROOT).items():
            self.assertEqual((ROOT / "evidence/table6/replacement" / name).read_bytes(), expected.encode("utf-8"))

    def test_manifest_snapshot_is_reproducible_and_rejects_drift(self) -> None:
        from scripts.build_release_archive import write_manifest_snapshot

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifests").mkdir()
            data = b"test artifact\n"
            (root / "README.md").write_bytes(data)
            inventory = {"files": [{"path": "README.md", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}
            (root / "manifests/files.json").write_text(json.dumps(inventory), encoding="utf-8")
            (root / "SHA256SUMS.txt").write_text("test", encoding="utf-8")
            first = root / "first.zip"
            second = root / "second.zip"
            write_manifest_snapshot(root, first, "artifact/")
            write_manifest_snapshot(root, second, "artifact/")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            (root / "README.md").write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "snapshot source changed"):
                write_manifest_snapshot(root, root / "changed.zip", "artifact/")

    def test_table6_progress_update_gate(self) -> None:
        from scripts.update_table6_progress import (
            progress_from_snapshot,
            progress_record_issues,
            progress_summary,
            progress_transition_issues,
        )

        previous = {
            "schema_version": 1,
            "checked_server_local": "2026-09-27 17:19:25",
            "last_event_server_local": "2026-09-27 17:17:57",
            "latest_sampled_log_server_local": "2026-09-27 17:19:25",
            "completed": 30,
            "running": 75,
            "queued": 45,
            "failed": 0,
            "all_csv_files": 61,
            "scheduler_active": True,
            "sampled_logs_advancing": True,
            "error_pattern_files": 0,
            "remote_result_root": "campaign",
            "final": False,
        }
        current = dict(previous)
        current.update(
            checked_server_local="2026-09-27 17:21:00",
            last_event_server_local="2026-09-27 17:20:30",
            latest_sampled_log_server_local="2026-09-27 17:21:00",
            completed=31,
            queued=44,
            all_csv_files=63,
        )
        self.assertEqual(progress_record_issues(current, 150), [])
        self.assertEqual(progress_transition_issues(previous, current), [])

        stale = dict(current, checked_server_local=previous["checked_server_local"])
        self.assertIn(
            "checked_server_local must advance beyond the recorded snapshot",
            progress_transition_issues(previous, stale),
        )
        regressing = dict(current, completed=29, queued=46, all_csv_files=59)
        issues = progress_transition_issues(previous, regressing)
        self.assertIn("completed cannot decrease", issues)
        self.assertIn("all_csv_files cannot decrease", issues)

        impossible_time = dict(
            current,
            last_event_server_local="2026-09-27 17:22:00",
        )
        self.assertIn(
            "last_event_server_local cannot be later than checked_server_local",
            progress_record_issues(impossible_time, 150),
        )

        snapshot = dict(current, schema_version=1, final=False, probe="test")
        imported = progress_from_snapshot(snapshot, 150)
        self.assertEqual(imported["completed"], 31)
        self.assertFalse(imported["final"])
        self.assertEqual(
            progress_summary(imported),
            "updated Table 6 progress: completed=31 running=75 queued=44 failed=0",
        )
        with self.assertRaisesRegex(ValueError, "schema_version"):
            progress_from_snapshot(dict(snapshot, schema_version=2), 150)
        invalid_root = dict(imported, remote_result_root="../campaign")
        self.assertIn(
            "remote_result_root must be one non-empty basename",
            progress_record_issues(invalid_root, 150),
        )
        invalid_windows_root = dict(imported, remote_result_root="..\\campaign")
        self.assertIn(
            "remote_result_root must be one non-empty basename",
            progress_record_issues(invalid_windows_root, 150),
        )

    def test_table6_structured_progress_probe(self) -> None:
        from scripts.table6_progress_probe import collect_progress

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name) / "campaign"
            scheduler = root / "scheduler_main"
            scripts_dir = scheduler / "scripts"
            done_dir = scheduler / "done"
            logs_dir = scheduler / "job_logs"
            state_dir = scheduler / "state"
            for directory in (scripts_dir, done_dir, logs_dir, state_dir):
                directory.mkdir(parents=True, exist_ok=True)

            for job_id in (1, 2, 3):
                stem = f"job_{job_id:05d}_fixture"
                (scripts_dir / f"{stem}.sh").write_text("#!/bin/sh\n", encoding="utf-8")
                (logs_dir / f"{stem}.log").write_text("INFO running\n", encoding="utf-8")
            (done_dir / "job_00001_fixture.exit").write_text("0\n", encoding="utf-8")
            (done_dir / "job_00002_fixture.exit").write_text("2\n", encoding="utf-8")
            (state_dir / "running_jobs.json").write_text("{}\n", encoding="utf-8")
            (root / "one.csv").write_text("a\n1\n", encoding="utf-8")
            nested = root / "main" / "point"
            nested.mkdir(parents=True)
            (nested / "two.csv").write_text("b\n2\n", encoding="utf-8")

            snapshot = collect_progress(root, 5, True, 0)
            self.assertEqual(snapshot["completed"], 1)
            self.assertEqual(snapshot["failed"], 1)
            self.assertEqual(snapshot["running"], 1)
            self.assertEqual(snapshot["queued"], 2)
            self.assertEqual(snapshot["dispatched"], 3)
            self.assertEqual(snapshot["exit_files"], 2)
            self.assertEqual(snapshot["all_csv_files"], 2)
            self.assertEqual(snapshot["error_pattern_files"], 0)
            self.assertFalse(snapshot["sampled_logs_advancing"])

            (logs_dir / "job_00003_fixture.log").write_text(
                "Traceback (most recent call last):\n", encoding="utf-8"
            )
            snapshot = collect_progress(root, 5, True, 0)
            self.assertEqual(snapshot["error_pattern_files"], 1)

    def test_table6_import_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            temp = Path(temp_name)
            input_root = temp / "campaign"
            result_dir = input_root / "main" / "points" / "driving_milan" / "k1" / "r0p1" / "s1"
            result_dir.mkdir(parents=True)
            result_path = result_dir / "edge_experiments_all_results.csv"
            result_fields = [
                "case", "policy", "seed", "total_slots", "total_arrival_rate",
                "fixed_k", "dcnc_solver", "dynvmp_calls",
                "dynvmp_wall_time_sec", "simulation_wall_time_sec",
            ]
            with result_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=result_fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "case": "driving_milan",
                        "policy": "DCNC-DAG",
                        "seed": 1,
                        "total_slots": 100000,
                        "total_arrival_rate": 0.1,
                        "fixed_k": 1,
                        "dcnc_solver": "dynvmp_bridge",
                        "dynvmp_calls": 10,
                        "dynvmp_wall_time_sec": 2.5,
                        "simulation_wall_time_sec": 3.0,
                    }
                )
            commands_path = temp / "commands.csv"
            command_fields = [
                "case", "K", "total_arrival_rate", "seed", "slots", "policy",
                "solver", "output_dir",
            ]
            with commands_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=command_fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "case": "driving_milan",
                        "K": 1,
                        "total_arrival_rate": 0.1,
                        "seed": 1,
                        "slots": 100000,
                        "policy": "DCNC-DAG",
                        "solver": "dynvmp_bridge",
                        "output_dir": "campaign/main/points/driving_milan/k1/r0p1/s1",
                    }
                )
            output_root = temp / "imported"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "import_table6_results.py"),
                    "--input-root", str(input_root),
                    "--output-root", str(output_root),
                    "--commands-csv", str(commands_path),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            imported = (
                output_root / "driving_milan" / "k1" / "r0p1" / "s1"
                / "edge_experiments_all_results.csv"
            )
            self.assertEqual(imported.read_bytes(), result_path.read_bytes())
            report = json.loads(
                (output_root / "import_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["imported_jobs"], 1)
            repeated = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "import_table6_results.py"),
                    "--input-root", str(input_root),
                    "--output-root", str(output_root),
                    "--commands-csv", str(commands_path),
                ],
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertNotEqual(repeated.returncode, 0, repeated.stdout)
            self.assertIn("refusing to overwrite", repeated.stdout)

    def test_integrity_manifest_covers_nested_evidence(self) -> None:
        paths = {
            item["path"]
            for item in json.loads(
                (ROOT / "manifests" / "files.json").read_text(encoding="utf-8")
            )["files"]
        }
        self.assertIn(
            "evidence/lp_capacity/results/canonical/metadata.json",
            paths,
        )
        self.assertNotIn("third_party/alib/alib/__init__.pyc", paths)

    def test_nested_lp_manifest_excludes_generated_files(self) -> None:
        from scripts.maintain_artifact import (
            is_generated_path,
            refresh_lp_manifest,
        )

        actual_root = ROOT / "evidence" / "lp_capacity"
        actual_manifest = actual_root / "SHA256SUMS.txt"
        actual_entries = {}
        for line in actual_manifest.read_text(encoding="utf-8").splitlines():
            expected_hash, relative = line.split("  ", 1)
            parsed = PurePosixPath(relative)
            self.assertFalse(parsed.is_absolute(), relative)
            self.assertNotIn("..", parsed.parts, relative)
            self.assertFalse(is_generated_path(parsed.parts), relative)
            path = actual_root.joinpath(*parsed.parts)
            self.assertTrue(path.is_file(), relative)
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest(),
                expected_hash,
                relative,
            )
            self.assertNotIn(relative, actual_entries)
            actual_entries[relative] = expected_hash
        expected_paths = {
            path.relative_to(actual_root).as_posix()
            for path in actual_root.rglob("*")
            if path.is_file()
            and path != actual_manifest
            and not is_generated_path(path.relative_to(actual_root).parts)
        }
        self.assertEqual(set(actual_entries), expected_paths)

        with tempfile.TemporaryDirectory() as temp_name:
            repo = Path(temp_name)
            lp_root = repo / "evidence" / "lp_capacity"
            cache = lp_root / "scripts" / "__pycache__"
            cache.mkdir(parents=True)
            (lp_root / "result.csv").write_text(
                "value\n1\n", encoding="utf-8", newline="\n"
            )
            (cache / "stale.cpython-310.pyc").write_bytes(b"bytecode")
            egg_info = lp_root / "package.egg-info"
            egg_info.mkdir()
            (egg_info / "PKG-INFO").write_text(
                "generated", encoding="utf-8", newline="\n"
            )
            (lp_root / ".coverage").write_bytes(b"generated")

            refresh_lp_manifest(repo)
            manifest = (lp_root / "SHA256SUMS.txt").read_text(
                encoding="utf-8"
            )
            self.assertIn("  result.csv\n", manifest)
            self.assertNotIn("__pycache__", manifest)
            self.assertNotIn(".egg-info", manifest)
            self.assertNotIn(".coverage", manifest)


if __name__ == "__main__":
    unittest.main()
