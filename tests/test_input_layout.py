from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class InputLayoutTests(unittest.TestCase):
    def test_migration_preserves_all_inputs(self) -> None:
        inventory = json.loads((ROOT / "manifests/input_layout.json").read_text(encoding="utf-8"))
        entries = inventory["files"]
        self.assertEqual(len(entries), 104)
        self.assertEqual(len({entry["old_path"] for entry in entries}), 104)
        self.assertEqual(len({entry["new_path"] for entry in entries}), 104)
        self.assertFalse((ROOT / "legacy_inputs").exists())
        for entry in entries:
            with self.subTest(path=entry["new_path"]):
                target = ROOT / entry["new_path"]
                self.assertTrue(target.is_file())
                if entry["comparison"] == "byte-identical":
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), entry["original_sha256"])
                elif entry["comparison"] == "config-paths-only":
                    config = json.loads(target.read_text(encoding="utf-8"))
                    self.assertTrue(config["network"]["file"].startswith("../topologies/"))
                    config["network"]["file"] = config["network"]["file"].replace("../topologies/", "Network/", 1)
                    for service in config["service_dags"]:
                        self.assertTrue(service["file"].startswith("../dags/"))
                        service["file"] = service["file"].replace("../dags/", "DAG/", 1)
                    canonical = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
                    self.assertEqual(hashlib.sha256(canonical).hexdigest(), entry["canonical_json_sha256"])
                else:
                    self.assertEqual(entry["comparison"], "maintained-helper")

    def test_all_configuration_references_resolve(self) -> None:
        configs = sorted((ROOT / "inputs/configs").glob("*.json"))
        self.assertEqual(len(configs), 56)
        for path in configs:
            config = json.loads(path.read_text(encoding="utf-8"))
            references = [config["network"]["file"]] + [service["file"] for service in config["service_dags"]]
            for reference in references:
                with self.subTest(config=path.name, reference=reference):
                    target = (path.parent / reference).resolve()
                    self.assertTrue(target.is_relative_to(ROOT / "inputs"))
                    self.assertTrue(target.is_file())

    def test_all_bundled_configurations_load(self) -> None:
        from dcnc_sim.workloads import load_config

        for path in sorted((ROOT / "inputs/configs").glob("*.json")):
            with self.subTest(config=path.name):
                network, commodities = load_config(path)
                self.assertTrue(network.node_capacities)
                self.assertTrue(commodities)

    def test_workflow_loader_accepts_old_config_argument(self) -> None:
        from scripts.run_workflow_case import load_explicit_config

        name = "config_workflow_srasearch22_random_allnodes.json"
        network, commodities = load_explicit_config(Path("legacy_inputs") / name)
        current_network, current_commodities = load_explicit_config(ROOT / "inputs/configs" / name)
        self.assertEqual(network.node_capacities, current_network.node_capacities)
        self.assertEqual(network.edge_capacities, current_network.edge_capacities)
        self.assertEqual(len(commodities), len(current_commodities))

    def test_new_and_old_configuration_paths(self) -> None:
        from dcnc_sim.inputs import CONFIG_ROOT, resolve_config_path
        from dcnc_sim.workloads import load_config, load_legacy_config

        name = "config_driving_Milan.json"
        expected = (CONFIG_ROOT / name).resolve()
        for argument in (name, "inputs/configs/" + name, "legacy_inputs/" + name, ROOT / "legacy_inputs" / name, expected):
            with self.subTest(argument=str(argument)):
                self.assertEqual(resolve_config_path(argument), expected)
        current_network, current_commodities = load_config(name)
        old_network, old_commodities = load_legacy_config("legacy_inputs/" + name)
        self.assertEqual(current_network.node_capacities, old_network.node_capacities)
        self.assertEqual(current_network.edge_capacities, old_network.edge_capacities)
        self.assertEqual(len(current_commodities), len(old_commodities))

    def test_explicit_configuration_is_not_shadowed(self) -> None:
        from dcnc_sim.inputs import resolve_config_path
        from dcnc_sim.workloads import load_config

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config_driving_Milan.json"
            original = ROOT / "inputs/configs" / path.name
            config = json.loads(original.read_text(encoding="utf-8"))
            config["network"]["file"] = str((original.parent / config["network"]["file"]).resolve())
            for service in config["service_dags"]:
                service["file"] = str((original.parent / service["file"]).resolve())
            path.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(resolve_config_path(path), path.resolve())
            network, commodities = load_config(path)
            self.assertTrue(network.node_capacities)
            self.assertTrue(commodities)
            missing = path.parent / "missing" / path.name
            self.assertEqual(resolve_config_path(missing), missing.resolve())
            with self.assertRaises(FileNotFoundError):
                load_config(missing)

    def test_moe_provenance_rejects_non_path_changes(self) -> None:
        from scripts.verify_moe_censored import historical_source_bytes, verify_results
        from unittest.mock import patch

        protocol = json.loads((ROOT / "evidence/moe_censored/protocol.json").read_text(encoding="utf-8"))
        for relative, expected in protocol["source_sha256"].items():
            self.assertEqual(hashlib.sha256(historical_source_bytes(ROOT, relative)).hexdigest(), expected)
        original_read = Path.read_bytes

        for relative in ("scripts/run_skewed_moe_milan.py", "inputs/topologies/Milan.json"):
            target = ROOT / relative

            def tampered_read(path: Path) -> bytes:
                content = original_read(path)
                return content + b"\n" if path == target else content

            with self.subTest(path=relative), patch.object(Path, "read_bytes", tampered_read):
                with self.assertRaisesRegex(ValueError, "MoE simulator source"):
                    verify_results(ROOT)

    def test_workflow_command_matrix_uses_current_paths(self) -> None:
        import csv
        import shlex

        path = ROOT / "inputs/command_csv/workflow_random_allnodes_final_50000_seed0_dense_v2.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                arguments = shlex.split(row["command"])
                config = arguments[arguments.index("--config") + 1]
                self.assertEqual(config, "inputs/configs/" + row["config"])
                self.assertTrue((ROOT / config).is_file())


if __name__ == "__main__":
    unittest.main()
