import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaffold_plan import load_scaffold_plan, ScaffoldPlan, ScaffoldPlanError  # noqa: E402


class ScaffoldPlanTests(unittest.TestCase):
    def test_loads_markdown_cc(self):
        sp = load_scaffold_plan("markdown-CC")
        self.assertIsInstance(sp, ScaffoldPlan)
        self.assertEqual(sp.system_shape, "markdown-CC")
        self.assertEqual(sp.criticality_model_policy["critical"]["primary_model_tier"], "high")
        self.assertIn("requires_cron", sp.allowed_resource_claims)
        self.assertNotIn("requires_external_network", sp.allowed_resource_claims)
        self.assertEqual(len(sp.control_plane), 10)
        self.assertEqual(sp.agent_scripts_dir, "agents/scripts")
        self.assertTrue(len(sp.i9_coverage_files) >= 1)

    def test_unknown_shape_fails_closed(self):
        with self.assertRaises(ScaffoldPlanError):
            load_scaffold_plan("python-service")  # no scaffold-plan file -> fail, not default


if __name__ == "__main__":
    unittest.main()
