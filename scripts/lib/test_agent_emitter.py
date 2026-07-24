"""Tests for the agent-layer emitter (stdlib unittest; pip-install-free).

Emits the /agents/ tree from a validated EmissionPlan against the REAL agent
templates into a temp staging dir, and asserts: structure, placeholder
exhaustion (no {{KEY}} survives), the tier-name-in-prompt / resolved-model-in-
script split, script executability, and foundation-only mode emits nothing.
"""

import copy
import json
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_emitter  # type: ignore  # noqa: E402
from agent_emitter import emit_agent_layer  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from generator import PLACEHOLDER_RE  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


class AgentEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _emit(self, plan_dict):
        plan = validate_emission_plan(plan_dict, self.contract)
        self._tmp = tempfile.TemporaryDirectory()
        staging = Path(self._tmp.name)
        written = emit_agent_layer(plan, staging, REPO_ROOT)
        return staging, written

    def tearDown(self):
        tmp = getattr(self, "_tmp", None)
        if tmp is not None:
            tmp.cleanup()

    def test_emits_full_agent_tree(self):
        staging, written = self._emit(_valid_plan())
        a = staging / "agents"
        for rel in ["prompts/orchestrator_prompt.md", "prompts/qa_agent_prompt.md",
                    "prompts/researcher_prompt.md", "scripts/researcher.sh",
                    "cron/cron_config.md", "roster.md"]:
            self.assertTrue((a / rel).exists(), f"missing emitted file: agents/{rel}")
        self.assertEqual(len(written), 6)

    def test_placeholder_exhaustion(self):
        # Emitting at all proves fail-fast covered every placeholder; this re-asserts
        # no {{KEY}} survived in any emitted artifact.
        staging, written = self._emit(_valid_plan())
        for p in written:
            text = p.read_text(encoding="utf-8")
            leftover = PLACEHOLDER_RE.findall(text)
            self.assertEqual(leftover, [], f"unsubstituted placeholder(s) in {p.name}: {leftover}")

    def test_high_risk_protective_sequence_in_prompts(self):
        # The high-risk protective sequence must live IN the agent prompts themselves
        # (self-contained — LLMs ignore referenced files under load), not only in a
        # referenced doctrine doc. Assert it carries through emission unchanged into
        # BOTH the orchestrator (verbatim copy) and a sample specialist (substituted).
        staging, _ = self._emit(_valid_plan())
        orchestrator_text = (staging / "agents/prompts/orchestrator_prompt.md").read_text()
        sample_agent_text = (staging / "agents/prompts/researcher_prompt.md").read_text()
        for prompt_text in (orchestrator_text, sample_agent_text):
            low = prompt_text.lower()
            for anchor in ["protective sequence", "back up", "confirm the real state",
                           "pre-write receipt", "verify afterward"]:
                self.assertIn(anchor, low, f"missing protective-sequence anchor: {anchor!r}")

    def test_never_compress_invariant_structural_in_both_prompts(self):
        # Anti-overfit / negative test: the four safety steps and the never-skip /
        # never-compress-step-4 language must be present as PROSE in BOTH emitted agent
        # prompts. The maturity ceremony only quiets NARRATION; it must never be able to
        # drop a safety step or the mandatory operator-approval (step 4). That guarantee
        # is structural in the prompt text, not a runtime decision — so assert the exact
        # load-bearing phrases survive emission verbatim into both prompts.
        staging, _ = self._emit(_valid_plan())
        orchestrator_text = (staging / "agents/prompts/orchestrator_prompt.md").read_text()
        sample_agent_text = (staging / "agents/prompts/researcher_prompt.md").read_text()
        for label, prompt_text in (("orchestrator", orchestrator_text),
                                    ("specialist", sample_agent_text)):
            low = prompt_text.lower()
            # All four functional safety steps name the action they take.
            for step_phrase in ("back up", "confirm the real state",
                                "get explicit operator approval", "verify afterward"):
                self.assertIn(step_phrase, low,
                              f"{label} prompt missing safety step phrase: {step_phrase!r}")
            # Never-skip-any-step language.
            self.assertIn("never skip", low,
                          f"{label} prompt missing the never-skip-a-step guarantee")
            # Step 4 (operator approval) must be called out as non-compressible /
            # always-required at every maturity level.
            self.assertIn("never compress step 4", low,
                          f"{label} prompt missing the explicit never-compress-step-4 guarantee")
            self.assertIn("at every maturity level", low,
                          f"{label} prompt does not bind approval to every maturity level")
            # The narration-only nature of maturity quieting is stated (it reduces
            # wordiness on steps 1/3/5, never the approval).
            self.assertIn("less wordy", low,
                          f"{label} prompt does not scope maturity to narration (wordiness) only")

    def test_project_name_substituted(self):
        staging, _ = self._emit(_valid_plan())
        orch = (staging / "agents/prompts/orchestrator_prompt.md").read_text()
        self.assertIn("demo", orch)

    def test_tier_name_in_prompt_resolved_model_in_script(self):
        # The split: prompt carries the tier NAME 'standard'; the invocation script
        # carries the RESOLVED model string 'model-standard' (never the bare tier name as --model).
        staging, _ = self._emit(_valid_plan())
        prompt = (staging / "agents/prompts/researcher_prompt.md").read_text()
        script = (staging / "agents/scripts/researcher.sh").read_text()
        self.assertIn("standard", prompt)                       # tier name present in prompt
        self.assertIn('AGENT_MODEL="model-standard"', script)   # resolved model in script
        self.assertNotIn('AGENT_MODEL="standard"', script)      # NOT the bare tier name

    def test_script_is_executable(self):
        staging, _ = self._emit(_valid_plan())
        script = staging / "agents/scripts/researcher.sh"
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR, "invocation script is not executable")

    def test_roster_lists_agent(self):
        staging, _ = self._emit(_valid_plan())
        roster = (staging / "agents/roster.md").read_text()
        self.assertIn("researcher", roster)
        self.assertIn("Orchestrator", roster)
        self.assertIn("QA", roster)

    def test_foundation_only_emits_nothing(self):
        import copy
        p = copy.deepcopy(_valid_plan())
        p["foundation_only_mode"] = True
        p["agents"] = []  # I7: foundation-only forbids agents
        staging, written = self._emit(p)
        self.assertEqual(written, [])
        self.assertFalse((staging / "agents").exists())

    # --- T7 / C-008: cron-claim consumption into the emitted cron_config.md ---

    @staticmethod
    def _cron_plan():
        """A valid plan whose single agent carries a cron cadence (the requires_cron
        path: assembler stamps orchestrator.schedule onto the agent's cron_cadence)."""
        import copy
        p = copy.deepcopy(_valid_plan())
        p["agents"][0]["cron_cadence"] = "0 * * * *"
        return p

    def _cron_entry_rows(self, staging):
        """The cron_config.md table rows that name the scheduled agent 'researcher'."""
        cron = (staging / "agents/cron/cron_config.md").read_text()
        rows = [ln for ln in cron.splitlines()
                if ln.lstrip().startswith("|") and "researcher" in ln]
        return cron, rows

    def test_cron_agent_cadence_reaches_cron_config(self):
        # The requires_cron agent's cadence must reach the emitted cron config as a
        # scheduled entry — today the emitter copies the static template verbatim and
        # the cadence is dropped on the floor.
        staging, _ = self._emit(self._cron_plan())
        cron, rows = self._cron_entry_rows(staging)
        self.assertTrue(rows, "no cron table row for the requires_cron agent 'researcher'")
        self.assertTrue(any("0 * * * *" in ln for ln in rows),
                        "the agent's cron cadence did not reach its cron_config row")
        self.assertNotIn("No entries yet", cron,
                         "cron config still shows the empty-state note despite a scheduled agent")

    def test_scheduled_job_invokes_orchestrator_by_default(self):
        # Control-plane rule: a scheduled job invokes the Orchestrator (control plane) by
        # default; directly scheduling the specialist (agents/scripts/<id>.sh) is the
        # declared exception, not the default.
        staging, _ = self._emit(self._cron_plan())
        _cron, rows = self._cron_entry_rows(staging)
        self.assertTrue(rows)
        self.assertTrue(any("orchestrator_prompt.md" in ln for ln in rows),
                        "scheduled entry does not invoke the Orchestrator by default")
        self.assertFalse(any("scripts/researcher.sh" in ln for ln in rows),
                         "scheduled entry directly invokes the specialist (declared exception, not the default)")
        # The invocation must carry the schedule trigger (which agent) — otherwise the
        # Orchestrator wakes on the cadence with no idea which scheduled work is due.
        self.assertTrue(any("agent=researcher" in ln for ln in rows),
                        "scheduled invocation does not carry the per-agent trigger")
        self.assertTrue(any("cadence=" in ln for ln in rows),
                        "scheduled invocation does not carry the cadence in the trigger")

    def test_no_cron_agents_preserves_empty_state_note(self):
        # Differential-gate baseline: with no scheduled agent the cron config keeps its
        # honest empty-state note (byte-equivalent to the prior verbatim copy). Guards
        # the empty branch so the retirement differential stays green.
        staging, _ = self._emit(_valid_plan())  # researcher carries no cron_cadence
        cron = (staging / "agents/cron/cron_config.md").read_text()
        self.assertIn("No entries yet", cron)


class RequirementsTxtDependencyDerivationTests(unittest.TestCase):
    """F-9 (Cut 1.4, Task 5): _emit_requirements_txt derives its content from the static
    preamble template PLUS any enrolled third-party packages already recorded in a capability
    dependency-enrollment manifest staged at agents/lib/external_write/operator_requirements.json
    (the file `wizard/agents/lib/external_write/dependency_enrollment.py` writes/reads at
    next-phase time on an existing project). An absent or empty manifest -- the fresh-emit case,
    and every system no capability has enrolled a package into -- must be byte-identical to the
    preamble alone (back-compat)."""

    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _writes_back_plan(self):
        plan_dict = copy.deepcopy(_valid_plan())
        plan_dict["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = json.dumps([
            {"id": "acme_crm", "name": "Acme CRM", "type": "CRM", "roles": ["boundary_output"]},
        ])
        return validate_emission_plan(plan_dict, self.contract)

    @staticmethod
    def _stage_bundle_template(root: Path, bundle_version: str) -> str:
        bundle_root_tpl = root / "foundation-bundles" / bundle_version / "templates" / "root"
        bundle_root_tpl.mkdir(parents=True)
        template_text = (Path(__file__).resolve().parents[2] / "templates" / "root"
                         / "requirements_template").read_text(encoding="utf-8")
        (bundle_root_tpl / "requirements_template").write_text(template_text, encoding="utf-8")
        return template_text

    def test_empty_manifest_is_byte_identical_to_preamble(self):
        plan = self._writes_back_plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_text = self._stage_bundle_template(root, plan.bundle_version)
            staging = root / "staging"
            staging.mkdir()

            out = agent_emitter._emit_requirements_txt(plan, staging, root)

            self.assertEqual(len(out), 1)
            self.assertEqual(out[0].read_text(encoding="utf-8"), template_text)

    def test_absent_manifest_directory_is_also_byte_identical(self):
        # No agents/lib/external_write/ directory at all yet (a completely fresh staging
        # dir, exactly what a real fresh emit looks like before this function is called).
        plan = self._writes_back_plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_text = self._stage_bundle_template(root, plan.bundle_version)
            staging = root / "staging"

            out = agent_emitter._emit_requirements_txt(plan, staging, root)

            self.assertEqual(out[0].read_text(encoding="utf-8"), template_text)

    def test_populated_manifest_appends_enrolled_packages_after_the_preamble(self):
        plan = self._writes_back_plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_text = self._stage_bundle_template(root, plan.bundle_version)
            staging = root / "staging"
            manifest_dir = staging / "agents" / "lib" / "external_write"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "operator_requirements.json").write_text(json.dumps([
                {"import_name": "googleapiclient", "package_name": "google-api-python-client",
                 "version": "2.149.0", "capability_id": "acme_gcal_sync"},
            ]), encoding="utf-8")

            out = agent_emitter._emit_requirements_txt(plan, staging, root)

            self.assertEqual(len(out), 1)
            text = out[0].read_text(encoding="utf-8")
            self.assertTrue(text.startswith(template_text),
                            "the static preamble must still be present, verbatim, at the top")
            self.assertIn("google-api-python-client==2.149.0", text)

    def test_malformed_manifest_degrades_to_preamble_only_not_a_crash(self):
        plan = self._writes_back_plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_text = self._stage_bundle_template(root, plan.bundle_version)
            staging = root / "staging"
            manifest_dir = staging / "agents" / "lib" / "external_write"
            manifest_dir.mkdir(parents=True)
            (manifest_dir / "operator_requirements.json").write_text("{ not valid json",
                                                                     encoding="utf-8")

            out = agent_emitter._emit_requirements_txt(plan, staging, root)

            self.assertEqual(out[0].read_text(encoding="utf-8"), template_text)


class RequirementsTxtRenderParityTests(unittest.TestCase):
    """Cut 1.4 Task 5 review fix (MINOR — pin render parity): agent_emitter's
    toolkit-side `_render_requirements_txt_content` deliberately duplicates a
    reduced form of the EMITTED module's own `render_requirements_txt` (see
    that function's own docstring for why a real cross-channel import is not
    used). A duplicate with no pinning test can silently diverge; this loads
    the real emitted module by file path (never on the toolkit's own
    sys.path at runtime) and asserts byte-for-byte identical output for the
    same manifest+preamble input, with no pre-existing requirements.txt to
    merge against (the only case the toolkit copy ever needs to reproduce)."""

    @staticmethod
    def _load_emitted_dependency_enrollment_module():
        import importlib.util
        path = (REPO_ROOT / "wizard" / "agents" / "lib" / "external_write"
                / "dependency_enrollment.py")
        spec = importlib.util.spec_from_file_location(
            "dependency_enrollment_emitted_for_parity_test", path)
        module = importlib.util.module_from_spec(spec)
        # Register in sys.modules BEFORE exec: the dataclass decorator's
        # postponed-annotation resolution (`from __future__ import
        # annotations` in the emitted module) looks the module up via
        # sys.modules[cls.__module__] while the class body is still
        # executing -- exec_module alone does not register it.
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    def test_render_output_matches_emitted_module_byte_for_byte(self):
        de = self._load_emitted_dependency_enrollment_module()
        preamble = "# preamble line\n# second preamble line\n"
        manifest_entries = [
            {"import_name": "googleapiclient", "package_name": "google-api-python-client",
             "version": "2.149.0", "capability_id": "acme_gcal_sync"},
            {"import_name": "yaml", "package_name": "PyYAML", "version": "6.0.2",
             "capability_id": "acme_config"},
        ]

        toolkit_output = agent_emitter._render_requirements_txt_content(
            preamble, manifest_entries)

        emitted_entries = [de.DependencyEntry.from_dict(e) for e in manifest_entries]
        emitted_output = de.render_requirements_txt(
            preamble, emitted_entries, existing_text=None)

        self.assertEqual(
            toolkit_output, emitted_output,
            "the toolkit-side renderer must produce byte-identical output to "
            "the emitted module's own renderer for the same manifest+preamble "
            "(fresh-emit case: no pre-existing requirements.txt to merge)")

    def test_render_output_matches_emitted_module_when_manifest_is_empty(self):
        de = self._load_emitted_dependency_enrollment_module()
        preamble = "# preamble only\n"

        toolkit_output = agent_emitter._render_requirements_txt_content(preamble, [])
        emitted_output = de.render_requirements_txt(preamble, [], existing_text=None)

        self.assertEqual(toolkit_output, emitted_output)


if __name__ == "__main__":
    unittest.main()
