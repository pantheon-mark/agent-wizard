import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaffold_plan import load_scaffold_plan, ScaffoldPlan, ScaffoldPlanError, derive_permission_map  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — divergent rosters so tests cannot pass by string-matching one
# example. Two independent plans with different agent names + different
# external surface names are exercised across the permission-derivation tests.
# ---------------------------------------------------------------------------

# Fixture A: a data-enrichment system writes back to "company_tracker"
_DEP_A_WRITES_BACK = {
    "id": "company_tracker",
    "name": "company_tracker",
    "type": "google_sheets",
    "roles": ["boundary_output"],
    "owner_agent_id": "enrichment-agent",
}
_DEP_A_INPUT_ONLY = {
    "id": "crm_export",
    "name": "crm_export",
    "type": "csv",
    "roles": ["boundary_input"],
    # No owner_agent_id — boundary_input deps don't have write owners.
}
_AGENT_RECORDS_A = [
    {
        "id": "enrichment-agent",
        "permitted_write_directories": ["work/agent_outputs", "agents/checkpoints"],
        "operator_facing": False,
        "deliverable_root": "deliverables",
    },
    {
        "id": "report-agent",
        "permitted_write_directories": ["work/agent_outputs", "agents/checkpoints"],
        "operator_facing": True,
        "deliverable_root": "deliverables",
    },
]
_DEPS_A = [_DEP_A_WRITES_BACK, _DEP_A_INPUT_ONLY]

# Fixture B: a finance system writes back to "budget_sheet" — different agent names,
# different surface name, proving the derivation generalises beyond fixture A.
_DEP_B_WRITES_BACK = {
    "id": "budget_sheet",
    "name": "budget_sheet",
    "type": "google_sheets",
    "roles": ["boundary_output"],
    "owner_agent_id": "finance-processor",
}
_AGENT_RECORDS_B = [
    {
        "id": "finance-processor",
        "permitted_write_directories": ["work/agent_outputs"],
        "operator_facing": False,
        "deliverable_root": "deliverables",
    },
    {
        "id": "summary-writer",
        "permitted_write_directories": ["work/agent_outputs"],
        "operator_facing": True,
        "deliverable_root": "deliverables",
    },
]
_DEPS_B = [_DEP_B_WRITES_BACK]

# Fixture C: a read-only pipeline — NO writes-back dependency.
_DEP_C_INPUT_ONLY = {
    "id": "feed",
    "name": "feed",
    "type": "rss",
    "roles": ["boundary_input"],
}
_AGENT_RECORDS_C = [
    {
        "id": "digest-agent",
        "permitted_write_directories": ["work/agent_outputs"],
        "operator_facing": False,
        "deliverable_root": "deliverables",
    },
]
_DEPS_C = [_DEP_C_INPUT_ONLY]


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


class PermissionMapTests(unittest.TestCase):
    """Tests for derive_permission_map — external-write targets + orchestrator carve-out."""

    def _load(self):
        return load_scaffold_plan("markdown-CC")

    # ------------------------------------------------------------------
    # Test 1: owning agent's permitted set includes the external surface
    # ------------------------------------------------------------------

    def test_owning_agent_gets_external_surface_fixture_a(self):
        """Fixture A: enrichment-agent owns company_tracker (boundary_output) ->
        its permitted set must include 'company_tracker'."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_A, _DEPS_A)
        self.assertIn("company_tracker", pmap["enrichment-agent"])

    def test_owning_agent_gets_external_surface_fixture_b(self):
        """Fixture B: finance-processor owns budget_sheet ->
        its permitted set must include 'budget_sheet'."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_B, _DEPS_B)
        self.assertIn("budget_sheet", pmap["finance-processor"])

    # ------------------------------------------------------------------
    # Test 2: orchestrator gets external surface (bound carve-out)
    # ------------------------------------------------------------------

    def test_orchestrator_gets_external_surface_fixture_a(self):
        """Fixture A: the orchestrator's permitted set includes 'company_tracker'
        so it can invoke the named external-write operations for that surface."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_A, _DEPS_A)
        self.assertIn("company_tracker", pmap["orchestrator"])

    def test_orchestrator_gets_external_surface_fixture_b(self):
        """Fixture B: orchestrator includes 'budget_sheet'."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_B, _DEPS_B)
        self.assertIn("budget_sheet", pmap["orchestrator"])

    # ------------------------------------------------------------------
    # Test 3: deliverable folders in the permission map
    # ------------------------------------------------------------------

    def test_deliverable_folder_in_permission_map_for_operator_facing_agent(self):
        """report-agent is operator_facing -> deliverable_root must appear in its permitted set."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_A, _DEPS_A)
        # report-agent has operator_facing=True and deliverable_root='deliverables'
        self.assertIn("deliverables", pmap["report-agent"])

    def test_deliverable_folder_in_permission_map_multi_fixture(self):
        """summary-writer (fixture B) is operator_facing -> deliverable_root in its permitted set."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_B, _DEPS_B)
        self.assertIn("deliverables", pmap["summary-writer"])

    # ------------------------------------------------------------------
    # Test 4a: ANTI-OVERFIT — non-owning agents do NOT get the surface
    # ------------------------------------------------------------------

    def test_non_owning_agent_does_not_get_external_surface(self):
        """report-agent does NOT own company_tracker -> 'company_tracker' must NOT
        appear in its permitted set (no dead grant)."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_A, _DEPS_A)
        self.assertNotIn("company_tracker", pmap["report-agent"])

    def test_non_owning_agent_does_not_get_other_fixtures_surface(self):
        """summary-writer (fixture B) does not own budget_sheet -> no grant."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_B, _DEPS_B)
        self.assertNotIn("budget_sheet", pmap["summary-writer"])

    # ------------------------------------------------------------------
    # Test 4b: ANTI-OVERFIT — no writes-back dep -> no spurious external surface grant
    # ------------------------------------------------------------------

    def test_no_writes_back_dep_no_external_surface_in_any_set(self):
        """Fixture C has no boundary_output dep. No agent's permitted set should
        contain 'feed' (which is boundary_input only, not a write target)."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_C, _DEPS_C)
        self.assertNotIn("feed", pmap.get("digest-agent", []))
        self.assertNotIn("feed", pmap.get("orchestrator", []))

    def test_no_writes_back_dep_orchestrator_entry_still_present(self):
        """Even with no writes-back dep the orchestrator entry exists in the map
        (it always owns control-plane paths); it just has no external surface grant."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_C, _DEPS_C)
        self.assertIn("orchestrator", pmap)

    # ------------------------------------------------------------------
    # Test 4c: boundary_input-only dep does NOT produce a write grant
    # ------------------------------------------------------------------

    def test_boundary_input_dep_does_not_produce_write_grant(self):
        """crm_export (fixture A) is boundary_input only — it must NOT appear in
        any permitted set (the system reads from it, not writes to it)."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_A, _DEPS_A)
        for agent_id, permitted in pmap.items():
            self.assertNotIn(
                "crm_export", permitted,
                msg=f"boundary_input dep 'crm_export' must not be granted to {agent_id}"
            )

    # ------------------------------------------------------------------
    # Test 4d: divergent surface names do not cross-contaminate
    # ------------------------------------------------------------------

    def test_fixture_a_surface_not_in_fixture_b_map(self):
        """company_tracker (fixture A) must not appear in fixture B's permission map."""
        sp = self._load()
        pmap_b = derive_permission_map(sp, _AGENT_RECORDS_B, _DEPS_B)
        for agent_id, permitted in pmap_b.items():
            self.assertNotIn(
                "company_tracker", permitted,
                msg=f"fixture-A surface 'company_tracker' must not appear in fixture-B map for {agent_id}"
            )

    def test_fixture_b_surface_not_in_fixture_a_map(self):
        """budget_sheet (fixture B) must not appear in fixture A's permission map."""
        sp = self._load()
        pmap_a = derive_permission_map(sp, _AGENT_RECORDS_A, _DEPS_A)
        for agent_id, permitted in pmap_a.items():
            self.assertNotIn(
                "budget_sheet", permitted,
                msg=f"fixture-B surface 'budget_sheet' must not appear in fixture-A map for {agent_id}"
            )

    # ------------------------------------------------------------------
    # Test 5: base permitted_write_directories are preserved
    # ------------------------------------------------------------------

    def test_base_permitted_dirs_preserved(self):
        """derive_permission_map must not DROP the agent's original permitted paths."""
        sp = self._load()
        pmap = derive_permission_map(sp, _AGENT_RECORDS_A, _DEPS_A)
        # enrichment-agent's base dirs must still be present.
        self.assertIn("work/agent_outputs", pmap["enrichment-agent"])
        self.assertIn("agents/checkpoints", pmap["enrichment-agent"])


if __name__ == "__main__":
    unittest.main()
