"""Task 12 — Python install (F-35 fix).

Dogfood finding F-35: emitted Python-shape systems ran on macOS's own end-of-life
system Python because the wizard install never checked for or installed a current
Python, used bare `python3`, and never created a venv or installed deps. The operator
(non-technical) had to fix this by hand.

Content-presence tests per the task's stated acceptance bar:
  1. `wizard/interview/00_env_check.md` carries a Python step, a stated floor (3.11),
     and the exact `brew install python@3.12` fix command.
  2. Both operator-facing install docs (the toolkit manual + the per-project manual
     template) document installing Python alongside the other four tools.
  3. `project_instructions.md`'s Version Pins section carries the Python end-of-life
     upkeep reminder (the "existing operator upkeep/notice mechanism" this task hooks
     into, per the brief).
  4. requirements.txt emission is gated + source-gated IDENTICALLY to the
     external_write lib / capability-descriptor-set emit (writes-back plans only, no
     dead file for a read-only system) -- mirrors test_capability_descriptor_set_emit.py.

Test runner: unittest (NOT pytest).
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

_LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(_LIB))

import agent_emitter  # type: ignore  # noqa: E402

REPO_ROOT = _LIB.resolve().parents[2]
ENV_CHECK = REPO_ROOT / "wizard" / "interview" / "00_env_check.md"
TOOLKIT_MANUAL = REPO_ROOT / "wizard" / "manual.md"
PROJECT_MANUAL = REPO_ROOT / "wizard" / "templates" / "root" / "manual.md"
PROJECT_INSTRUCTIONS = REPO_ROOT / "wizard" / "templates" / "root" / "project_instructions.md"
REQUIREMENTS_TEMPLATE = REPO_ROOT / "wizard" / "templates" / "root" / "requirements_template"

BREW_FIX_COMMAND = "brew install python@3.12"


class EnvCheckPythonStepTests(unittest.TestCase):
    """00_env_check.md carries the Python step, the floor, and the fix command."""

    def setUp(self):
        self.text = ENV_CHECK.read_text(encoding="utf-8")

    def test_file_exists(self):
        self.assertTrue(ENV_CHECK.is_file())

    def test_has_a_python_check(self):
        self.assertIn("Check 5: Python", self.text)

    def test_states_the_floor(self):
        self.assertIn("3.11", self.text)

    def test_recommends_3_12(self):
        self.assertIn("3.12", self.text)

    def test_names_exact_fix_command(self):
        self.assertIn(BREW_FIX_COMMAND, self.text)

    def test_never_blindly_trusts_bare_python3_alone(self):
        # The detection sequence must try a dedicated/verified interpreter before (or
        # instead of) bare `python3` -- not just `python3 --version` on its own.
        self.assertIn("python3.12", self.text)

    def test_writes_a_substep_completion_marker(self):
        self.assertIn("step_00_CHECK-5", self.text)

    def test_check_count_updated_from_four_to_five(self):
        self.assertIn("all five prerequisites", self.text)
        self.assertIn("Run all five checks", self.text)


class InstallDocsPythonStepTests(unittest.TestCase):
    """Both operator-facing install docs mention installing Python."""

    def test_toolkit_manual_documents_python_install(self):
        text = TOOLKIT_MANUAL.read_text(encoding="utf-8")
        self.assertIn(BREW_FIX_COMMAND, text)
        self.assertIn("Install Python", text)

    def test_project_manual_appendix_documents_python_install(self):
        text = PROJECT_MANUAL.read_text(encoding="utf-8")
        self.assertIn(BREW_FIX_COMMAND, text)
        self.assertIn("Python", text)

    def test_project_manual_references_venv_mechanism(self):
        text = PROJECT_MANUAL.read_text(encoding="utf-8")
        self.assertIn("requirements.txt", text)
        self.assertIn("start-session.sh", text)


class UpkeepReminderTests(unittest.TestCase):
    """The EOL upkeep reminder fits the existing Version Pins / credential-expiry
    upkeep-notice pattern in project_instructions.md."""

    def setUp(self):
        self.text = PROJECT_INSTRUCTIONS.read_text(encoding="utf-8")

    def test_version_pins_section_present(self):
        self.assertIn("## Version Pins", self.text)

    def test_python_eol_watch_present(self):
        self.assertIn("end-of-life", self.text)
        self.assertIn("{{PYTHON_FLOOR_VERSION}}", self.text)
        self.assertIn("{{PYTHON_EOL_CHECK_CADENCE}}", self.text)

    def test_conditional_on_requirements_txt_presence(self):
        # Framed so a non-Python system reads it as inapplicable, not as noise about a
        # feature it doesn't have.
        self.assertIn("requirements.txt", self.text)
        self.assertIn("does not apply", self.text)

    def test_default_placeholders_resolve(self):
        defaults = agent_emitter_scaffold_defaults()
        self.assertEqual(defaults["PYTHON_FLOOR_VERSION"], "3.11")
        self.assertTrue(defaults["PYTHON_EOL_CHECK_CADENCE"])


def agent_emitter_scaffold_defaults():
    import scaffold_emitter  # type: ignore
    return scaffold_emitter._default_scaffold_inputs()


def _writes_back_identity(extra=None):
    deps = [{"id": "sheet", "name": "Sheet", "type": "Spreadsheet", "roles": ["boundary_output"]}]
    if extra:
        deps.extend(extra)
    return json.dumps(deps)


def _writes_back_plan():
    from test_emission_plan import _valid_plan  # type: ignore
    from emission_plan import (  # type: ignore
        validate_emission_plan, load_contract, default_contract_path,
    )
    p = copy.deepcopy(_valid_plan())
    p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = _writes_back_identity()
    return validate_emission_plan(p, load_contract(default_contract_path()))


def _read_only_plan():
    from test_emission_plan import _valid_plan  # type: ignore
    from emission_plan import (  # type: ignore
        validate_emission_plan, load_contract, default_contract_path,
    )
    p = copy.deepcopy(_valid_plan())
    p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = json.dumps(
        [{"id": "rss", "name": "rss_feed", "type": "RSS", "roles": ["boundary_input"]}]
    )
    return validate_emission_plan(p, load_contract(default_contract_path()))


class RequirementsTxtEmitGatingTests(unittest.TestCase):
    """requirements.txt is emitted iff the plan is writes-back, source-gated on the bundle
    carrying the template -- mirrors test_capability_descriptor_set_emit.py exactly."""

    def test_read_only_emits_nothing(self):
        plan = _read_only_plan()
        with tempfile.TemporaryDirectory() as tmp:
            out = agent_emitter._emit_requirements_txt(plan, Path(tmp), REPO_ROOT)
        self.assertEqual(out, [], "a read-only system must get no requirements.txt")

    def test_writes_back_inert_when_bundle_lacks_template(self):
        # Against a synthetic bundle root that does NOT carry the template (simulates
        # every bundle prior to the cut that copies it in) -- inert, no crash.
        plan = _writes_back_plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "foundation-bundles" / plan.bundle_version / "templates").mkdir(
                parents=True)
            staging = root / "staging"
            staging.mkdir()
            out = agent_emitter._emit_requirements_txt(plan, staging, root)
        self.assertEqual(out, [])
        self.assertFalse((staging / "requirements.txt").exists())

    def test_writes_back_emits_requirements_txt_when_bundle_carries_template(self):
        plan = _writes_back_plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_root_tpl = root / "foundation-bundles" / plan.bundle_version / "templates" / "root"
            bundle_root_tpl.mkdir(parents=True)
            (bundle_root_tpl / "requirements_template").write_text(
                REQUIREMENTS_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
            staging = root / "staging"
            staging.mkdir()
            out = agent_emitter._emit_requirements_txt(plan, staging, root)
            self.assertEqual(len(out), 1)
            emitted = staging / "requirements.txt"
            self.assertTrue(emitted.is_file())
            self.assertEqual(emitted.read_text(encoding="utf-8"),
                              REQUIREMENTS_TEMPLATE.read_text(encoding="utf-8"))

    def test_emit_agent_layer_wiring_present_and_currently_inert_against_real_repo(self):
        """End-to-end through emit_agent_layer's REAL call site (not just the helper in
        isolation) against the REAL repo -- proves the wiring is reachable and does not
        crash. Currently inert (no requirements.txt) because _valid_plan()'s pinned
        bundle_version (v0.6.0) predates both the external_write lib and this template --
        the same source-gated-until-bundle-cut state test_capability_descriptor_set_emit.py
        documented for the descriptor set before its own bundle cut landed."""
        plan = _writes_back_plan()
        with tempfile.TemporaryDirectory() as tmp:
            staging = Path(tmp)
            written = agent_emitter.emit_agent_layer(plan, staging, REPO_ROOT)
            self.assertNotIn(staging / "requirements.txt", written)
            self.assertFalse((staging / "requirements.txt").exists())
            # But the ordinary agent tree still emits fully -- the new wiring is
            # additive, not a regression on the existing emit path.
            self.assertTrue((staging / "agents" / "roster.md").exists())


class ScaffoldExcludesRequirementsTemplateFromUnconditionalWalkTests(unittest.TestCase):
    """The unconditional root/ scaffold walk must never emit requirements_template
    itself -- only the conditional agent_emitter path does, gated on writes-back."""

    def test_requirements_template_basename_excluded(self):
        import scaffold_emitter  # type: ignore
        self.assertIn("requirements_template", scaffold_emitter.EXCLUDE_BASENAMES)


if __name__ == "__main__":
    unittest.main()
