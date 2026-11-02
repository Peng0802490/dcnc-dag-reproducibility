"""Independent reconstruction and source/conversion boundary checks."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from input_builders import (CONSTRUCTION, read_json, generate_roofnet, apply_capacities,
                            apply_access_dynamics, convert_workflow, validate_dag, verify_sources)
from rebuild_inputs import rebuild
from normalize_workflow_measurements import normalize, comparison


class InputBuilderTests(unittest.TestCase):
    def test_rebuild_matches_all_released_inputs(self):
        with tempfile.TemporaryDirectory(prefix=".test-inputs-", dir=ROOT) as tmp:
            self.assertEqual(len(rebuild(tmp, check=True)), 3)

    def test_source_snapshots_match_pinned_hashes(self):
        verify_sources()

    def test_roofnet_geometry_and_overlay_counts(self):
        recipe = read_json(CONSTRUCTION / "roofnet_recipe.json")
        base = generate_roofnet(recipe)
        original = copy.deepcopy(base)
        self.assertEqual(len(base["nodes"]), 38)
        self.assertEqual(len(base["edges"]), 262)
        pairs = {(e["from"], e["to"]) for e in base["edges"]}
        self.assertEqual(pairs, {(v, u) for u, v in pairs})
        net = apply_capacities(base, recipe["capacity_seed"])
        net = apply_access_dynamics(net, read_json(ROOT / recipe["access_config"]))
        self.assertEqual(sum(e["dynamic"] for e in net["edges"]), 70)
        self.assertTrue(all(e["p_on"] == .8 for e in net["edges"] if e["dynamic"]))
        self.assertTrue(all("p_on" not in e for e in net["edges"] if not e["dynamic"]))
        self.assertEqual(base, original)

    def test_sra_preserves_all_public_dependencies(self):
        public = convert_workflow("srasearch22", public_only=True)
        adapted = convert_workflow("srasearch22")
        self.assertEqual(len(public["nodes"]), 22)
        self.assertEqual(set(map(tuple, public["edges"])),
                         {(e["from"], e["to"]) for e in adapted["edges"]})

    def test_sipht_adaptations_are_explicit_and_counted(self):
        public = convert_workflow("sipht31", public_only=True)
        adapted = convert_workflow("sipht31")
        before = set(map(tuple, public["edges"]))
        after = {(e["from"], e["to"]) for e in adapted["edges"]}
        self.assertEqual((len(public["nodes"]), len(before), len(after)), (31, 34, 34))
        self.assertEqual(len(before - after), 7)
        self.assertEqual(len(after - before), 7)
        self.assertIn(("Blast_ID000023", "SRNA_ID000029"), before - after)

    def test_invalid_graph_and_endpoints_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            validate_dag({"a", "b"}, {("a", "b"), ("b", "a")})
        with self.assertRaisesRegex(ValueError, "unknown"):
            validate_dag({"a"}, {("a", "b")})
        with self.assertRaisesRegex(ValueError, "endpoint"):
            apply_access_dynamics({"nodes": [], "edges": []},
                                  {"service_dags": [{"sources": {"s": "missing"}}]})

    def test_prospective_normalization_and_missing_values(self):
        self.assertEqual(normalize(12, 4), 3)
        self.assertEqual(normalize(12, 4, maximum=2), 2)
        self.assertEqual(normalize(0, 4, minimum=.5), .5)
        self.assertIsNone(normalize("", 4))
        for scale in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                normalize(1, scale)
        with self.assertRaises(ValueError):
            normalize(-1, 1)

    def test_comparison_does_not_invent_missing_sipht_sizes(self):
        rows = comparison("sipht31", 1, 1)
        edges = [r for r in rows if r["metric"] == "xi"]
        self.assertEqual(len(edges), 34)
        self.assertTrue(all(r["new_normalized_value"] is None and r["status"] == "measurement_unavailable" for r in edges))
        self.assertTrue(all(r["archived_fixed_value"] != "" for r in edges))


if __name__ == "__main__":
    unittest.main()
