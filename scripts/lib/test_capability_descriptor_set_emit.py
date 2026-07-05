"""B2-T9a — the initial capability-descriptor-set emit wiring.

Pins the two required outcomes of T9a:

  (1) the COMPLETE initial descriptor set (base_declared_descriptors() + the operator's declared
      capability descriptors, all accepted:false) is what security/capability_descriptors.json is
      emitted with, and it PASSES the build-time coverage gate on a clean scan — i.e. a fresh
      writes-back system is NOT dead-on-arrival. This is checked with zero declared capabilities
      (base-only, the minimum every writes-back build carries) AND with a declared capability.
  (2) the emit is correctly GATED to writes-back systems only, mirroring the external_write lib
      emit, and source-gated on the bundle carrying the JSON template (inert until T9b), and when
      the bundle DOES carry it the emitted file is valid, parseable, coverage-passing JSON.

Also pins the derive-projection JSON template mechanism: the full-body
{{CAPABILITY_DESCRIPTORS_JSON}} placeholder is filled by the producer's JSON at emit through the
same strict fail-fast substitution every template uses (JSON single-braces pass through cleanly).

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
# The build-side coverage gate lives in the external_write package under wizard/agents/lib.
_AGENTS_LIB = _LIB.resolve().parents[1] / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

import capability_descriptor_registry as cdr  # type: ignore  # noqa: E402
import dependency_projection as dp  # type: ignore  # noqa: E402
import agent_emitter  # type: ignore  # noqa: E402
from generator import _substitute_placeholders  # type: ignore  # noqa: E402
from external_write.coverage_gate import evaluate_coverage_gate  # type: ignore  # noqa: E402

REPO_ROOT = _LIB.resolve().parents[2]
CANONICAL_TEMPLATE = REPO_ROOT / "wizard" / "templates" / "security" / "capability_descriptors.json"


def _writes_back_identity(extra=None):
    """A canonical EXTERNAL_DEPENDENCY_IDENTITY record with one writes-back dependency."""
    deps = [{"id": "sheet", "name": "Sheet", "type": "Spreadsheet", "roles": ["boundary_output"]}]
    if extra:
        deps.extend(extra)
    return json.dumps(deps)


class InitialDescriptorSetTest(unittest.TestCase):
    """Outcome 1: the producer yields the COMPLETE base+declared set, all accepted:false."""

    def test_base_only_when_no_declared_capabilities(self):
        # Zero declared capabilities (a bare writes-back surface, no descriptor fields): the set
        # is the base descriptors alone — still non-empty (every fresh writes-back build carries
        # the built-in guarded coverage).
        entries = cdr.build_initial_descriptor_set(_writes_back_identity())
        self.assertTrue(entries, "base descriptors must always be present")
        self.assertTrue(all(e["id"].startswith(cdr.BASE_DESCRIPTOR_ID_PREFIX) for e in entries),
                        "with no declared capability every entry is a base descriptor")

    def test_every_entry_is_unaccepted(self):
        ident = _writes_back_identity([
            {"id": "mailer", "name": "Mailer", "type": "SMTP", "roles": ["boundary_output"],
             "action_class": "send_execute", "risk_class": "irreversible_external"},
        ])
        entries = cdr.build_initial_descriptor_set(ident)
        self.assertTrue(entries)
        self.assertTrue(all(e["accepted"] is False for e in entries),
                        "D-B1-b: every emitted descriptor is accepted:false")

    def test_base_plus_declared_composition(self):
        ident = _writes_back_identity([
            {"id": "mailer", "name": "Mailer", "type": "SMTP", "roles": ["boundary_output"],
             "action_class": "send_execute", "risk_class": "reversible_external"},
        ])
        entries = cdr.build_initial_descriptor_set(ident)
        ids = [e["id"] for e in entries]
        # base entries precede declared; the declared 'mailer' is present.
        self.assertIn("mailer", ids)
        self.assertTrue(any(i.startswith(cdr.BASE_DESCRIPTOR_ID_PREFIX) for i in ids))
        base_idx = max(i for i, e in enumerate(entries)
                       if e["id"].startswith(cdr.BASE_DESCRIPTOR_ID_PREFIX))
        self.assertLess(base_idx, ids.index("mailer"),
                        "base entries must precede declared entries (deterministic order)")

    def test_deterministic(self):
        ident = _writes_back_identity([
            {"id": "mailer", "name": "Mailer", "type": "SMTP", "roles": ["boundary_output"],
             "action_class": "send_execute", "risk_class": "irreversible_external"},
        ])
        a = cdr.render_initial_descriptor_set_json(ident)
        b = cdr.render_initial_descriptor_set_json(ident)
        self.assertEqual(a, b)

    def test_render_is_valid_json_with_entry_shape(self):
        ident = _writes_back_identity([
            {"id": "mailer", "name": "Mailer", "type": "SMTP", "roles": ["boundary_output"],
             "action_class": "send_execute", "risk_class": "irreversible_external"},
        ])
        text = cdr.render_initial_descriptor_set_json(ident)
        parsed = json.loads(text)  # must parse
        self.assertIsInstance(parsed, list)
        for e in parsed:
            self.assertEqual(set(e.keys()), set(cdr.ENTRY_KEYS))


class FreshBuildPassesCoverageTest(unittest.TestCase):
    """Outcome 1, load-bearing: the emitted set passes the coverage gate on a clean scan — a
    fresh writes-back build is not dead-on-arrival."""

    def _assert_passes(self, ident):
        descriptor_set = json.loads(cdr.render_initial_descriptor_set_json(ident))
        decision = evaluate_coverage_gate(scan_violations=[], descriptor_set=descriptor_set)
        self.assertTrue(decision.passed,
                        f"coverage gate should PASS on the emitted set; failures={decision.failures}")
        # Specifically: no uncovered_mutator (the dead-on-arrival symptom).
        self.assertFalse([f for f in decision.failures if f.kind == "uncovered_mutator"])

    def test_base_only_passes(self):
        self._assert_passes(_writes_back_identity())

    def test_with_declared_capability_passes(self):
        self._assert_passes(_writes_back_identity([
            {"id": "mailer", "name": "Mailer", "type": "SMTP", "roles": ["boundary_output"],
             "action_class": "send_execute", "risk_class": "irreversible_external"},
        ]))

    def test_empty_descriptor_set_would_fail(self):
        # Negative control: without the base descriptors (the pre-T9a state), the gate fails
        # closed with uncovered_mutator — proving the base half is what rescues the build.
        decision = evaluate_coverage_gate(scan_violations=[], descriptor_set=[])
        self.assertFalse(decision.passed)
        self.assertTrue(any(f.kind == "uncovered_mutator" for f in decision.failures))


class TemplateSubstitutionTest(unittest.TestCase):
    """The JSON-via-placeholder mechanism: the canonical template is a full-body placeholder,
    and substituting the producer JSON yields valid, coverage-passing JSON."""

    def test_canonical_template_is_full_body_placeholder(self):
        body = CANONICAL_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("{{CAPABILITY_DESCRIPTORS_JSON}}", body)

    def test_substitution_produces_parseable_json(self):
        ident = _writes_back_identity([
            {"id": "mailer", "name": "Mailer", "type": "SMTP", "roles": ["boundary_output"],
             "action_class": "send_execute", "risk_class": "irreversible_external"},
        ])
        value = cdr.render_initial_descriptor_set_json(ident)
        body = CANONICAL_TEMPLATE.read_text(encoding="utf-8")
        result, _seen = _substitute_placeholders(body, {cdr.EMIT_FIELD: value},
                                                 template_name="capability_descriptors.json")
        parsed = json.loads(result)  # the emitted file is valid JSON
        self.assertIsInstance(parsed, list)
        decision = evaluate_coverage_gate(scan_violations=[], descriptor_set=parsed)
        self.assertTrue(decision.passed)


def _writes_back_plan(identity_json):
    from test_emission_plan import _valid_plan  # type: ignore
    from emission_plan import (  # type: ignore
        validate_emission_plan, load_contract, default_contract_path,
    )
    p = copy.deepcopy(_valid_plan())
    p["foundation_doc_inputs"]["EXTERNAL_DEPENDENCY_IDENTITY"] = identity_json
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


class EmitGatingTest(unittest.TestCase):
    """Outcome 2: writes-back -> descriptor set emitted; read-only -> not; source-gated on the
    bundle carrying the template (inert until T9b)."""

    def test_read_only_emits_nothing(self):
        plan = _read_only_plan()
        with tempfile.TemporaryDirectory() as tmp:
            out = agent_emitter._emit_capability_descriptor_set(plan, Path(tmp), REPO_ROOT)
        self.assertEqual(out, [], "a read-only system must get no descriptor set")

    def test_writes_back_source_gated_inert_until_bundle_cut(self):
        # The real repo bundle for the plan's version does not carry the template yet (T9b);
        # the emit must be a no-op (source-gated), NOT a crash.
        plan = _writes_back_plan(_writes_back_identity())
        with tempfile.TemporaryDirectory() as tmp:
            out = agent_emitter._emit_capability_descriptor_set(plan, Path(tmp), REPO_ROOT)
        self.assertEqual(out, [],
                         "inert until T9b copies the template into the bundle (source-gated)")

    def test_writes_back_emits_coverage_passing_json_when_bundle_carries_template(self):
        # Construct a temp build-repo-root whose bundle DOES carry the JSON template, exercising
        # the real emit path end-to-end (never-exercised path is a latent failure).
        plan = _writes_back_plan(_writes_back_identity([
            {"id": "mailer", "name": "Mailer", "type": "SMTP", "roles": ["boundary_output"],
             "action_class": "send_execute", "risk_class": "irreversible_external"},
        ]))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle_tpl = (root / "foundation-bundles" / plan.bundle_version /
                          "templates" / "security")
            bundle_tpl.mkdir(parents=True)
            (bundle_tpl / "capability_descriptors.json").write_text(
                CANONICAL_TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
            staging = root / "staging"
            staging.mkdir()
            out = agent_emitter._emit_capability_descriptor_set(plan, staging, root)
            self.assertEqual(len(out), 1)
            emitted = staging / "security" / "capability_descriptors.json"
            self.assertTrue(emitted.is_file())
            parsed = json.loads(emitted.read_text(encoding="utf-8"))
            self.assertTrue(all(e["accepted"] is False for e in parsed))
            decision = evaluate_coverage_gate(scan_violations=[], descriptor_set=parsed)
            self.assertTrue(decision.passed,
                            f"emitted set must pass coverage; failures={decision.failures}")


if __name__ == "__main__":
    unittest.main()
