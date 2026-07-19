"""Regression tests for the Cut-1 in-slice fix: replay-capsule persistence of
CAPABILITY_DESCRIPTORS_JSON, closing the upgrade-path gap where a freshly-emitted
FULL writes-back operator system (any bundle >= v0.10.0) could not survive its
FIRST apply_upgrade -- the capsule never carried the key the descriptors file's
render needs, so the replay-conformance gate refused with:

    replay-conformance gate FAILED: ... the target bundle template for
    'security/capability_descriptors.json' references placeholder(s)
    ['CAPABILITY_DESCRIPTORS_JSON'] that could not be resolved ...

Covers the fix's three parts (see external_review/phase3_cut1_capsule_descriptor_
persist_consult_2026-07-18.md "REVISED FIX" -- the authoritative adjudication --
and phase3_cut1_capsule_descriptor_persist_design_2026-07-18.md for root cause):

  (1) upstream hydration -- agent_emitter.ensure_capability_descriptor_emit_field
      fills plan.foundation_doc_inputs[CAPABILITY_DESCRIPTORS_JSON] (idempotent,
      writes-back plans only, existing value wins) BEFORE either the descriptor
      emitter or the replay-capsule builder read foundation_doc_inputs, so a fresh
      emit's capsule carries the key and its first upgrade does not refuse.
  (2) read-side JIT backfill -- upgrade_apply._backfill_capsule_capability_
      descriptors repairs an already-emitted (pre-fix) v2 capsule missing the key,
      IN-MEMORY only, immediately followed by the EXISTING replay-conformance
      base_hash check (never trusted blindly -- a producer-drifted derivation
      still fails closed with the gate's own plain-language refusal).
  (3) this file: the missing regression coverage whose absence hid the bug (the
      gate battery's synthetic capsule tests hand-construct persisted keys; the
      only real held-out e2e was pinned to v0.4.0 -> v0.5.0, pre-dating the
      descriptors contract).

Uses a synthetic (non-transcript) writes-back EmissionPlan against the REAL
v0.13.1 bundle (already fully cut in this repo) so these tests run unconditionally
-- no external transcript fixture prerequisite. See also the adapted throwaway
scratchpad/apply_e2e_v0140.py for a real-transcript proof of the same fix on the
v0.13.1 -> v0.14.0 cut specifically.

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

import agent_emitter  # noqa: E402
import capability_descriptor_registry as cdr  # noqa: E402
from build_intent import BuildIntent, AgentIntent, ResourceClaims  # noqa: E402
from dependency_projection import IDENTITY_FIELD  # noqa: E402
from emission_plan import validate_emission_plan, load_contract, default_contract_path  # noqa: E402
from emission_plan_assembler import assemble_emission_plan  # noqa: E402
from generator import _substitute_placeholders  # noqa: E402
from corpus_loader import load_corpus_pack  # noqa: E402
from model_tiers import load_model_tiers  # noqa: E402
from scaffold_plan import load_scaffold_plan  # noqa: E402
from test_emission_plan import _FOUNDATION_DOC_INPUTS, _valid_plan  # noqa: E402
from operator_system_emitter import generate_operator_system  # noqa: E402
from replay_capsule import REPLAY_CAPSULE_REL  # noqa: E402
from upgrade import load_operator_manifest, load_registry  # noqa: E402
from upgrade_apply import (  # noqa: E402
    apply_upgrade,
    UpgradeApplyError,
    APPLY_RESULT_APPLIED,
    APPLY_RESULT_PARTIAL,
    _replay_conformance_check,
    _render_version,
    _foundation_managed_entries,
    _backfill_capsule_capability_descriptors,
)

REPO_ROOT = _LIB.resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"
EP_CONTRACT = load_contract(default_contract_path())
SHAPE = "markdown-CC"

# The bundle this fix targets: >= v0.10.0 (the descriptors contract landed), a real
# already-cut operating-layer bundle, and NOT the latest (so a real upgrade-forward
# path — v0.13.1 -> v0.14.0 — exists via the shipped registry + migration manifest).
_SOURCE_VERSION = "v0.13.1"
_TARGET_VERSION = "v0.14.0"

_DECLARED_DEP = {
    "id": "tracker", "name": "company_tracker", "type": "Sheet",
    "roles": ["boundary_output"], "owner_agent_id": "researcher",
    "action_class": "send_execute", "risk_class": "irreversible_external",
}

_FOUNDATION_DOCS = [
    "vision.md", "approach.md", "technical_architecture.md",
    "execution_plan.md", "test_cases.md", "audit_framework.md",
]


def _agent():
    return AgentIntent(display_name="Researcher", function_summary="Gathers source material.",
                       role_intent="Gathers source material.", acceptance_signals=["non-empty summary"],
                       output_purpose="summary", criticality_tier="standard", resource_claims=ResourceClaims(),
                       confidence="high", insufficiency_flags=[], source_spans=["ARCH-2#1"])


def _writes_back_plan(bundle_version=_SOURCE_VERSION, identity=None, extra_fdi=None):
    """A validated writes-back EmissionPlan on a real, already-cut operating-layer
    bundle (default v0.13.1 -- the pre-v0.14.0 version the bug affects).

    Uses the REAL model-tier registry (model_tiers.load_model_tiers), NOT
    scaffold_plan's distributable placeholder default ("model-high" etc.) --
    matching what the real production emit path (interview_bridge.py) does, and
    what upgrade_apply._render_operating_layer's canonical replay re-derives via
    bundle_templates.derive_scaffold_render_inputs. Using the placeholder default
    here would make every operating-layer scaffold file (project_instructions.md,
    session_bootstrap.md, start-session.sh) fail replay-conformance for a reason
    UNRELATED to this fix (a test-fixture mismatch, not a real bug)."""
    deps = [dict(_DECLARED_DEP)] if identity is None else identity
    inp = dict(_FOUNDATION_DOC_INPUTS)
    inp[IDENTITY_FIELD] = json.dumps(deps)
    if extra_fdi:
        inp.update(extra_fdi)
    audit = {k: {"_source": "operator-content", "_derivation_class": "extraction",
                 "_decision_field": False, "_decision_kind": "none",
                 "_confirmation_state": "accepted", "_confirmed_at": "2026-05-30"}
             for k in inp}
    derived_record = dict(inp)
    derived_record["_audit"] = audit

    sp = load_scaffold_plan(SHAPE)
    bi = BuildIntent(derived_record=derived_record, agent_intents=[_agent()])
    d = assemble_emission_plan(
        bi, sp, load_corpus_pack(), model_tiers=load_model_tiers(SHAPE),
        bundle_version=bundle_version)
    return validate_emission_plan(d, EP_CONTRACT)


def _simple_writes_back_plan(bundle_version=_SOURCE_VERSION, identity=None, extra_fdi=None):
    """A lighter-weight writes-back plan for tests that exercise ONLY
    ensure_capability_descriptor_emit_field's pure dict logic (no template
    rendering) -- bypasses assemble_emission_plan's derived-record `_audit`
    envelope invariants (DR-9 forbids a blank/stub field value), which would
    otherwise reject a deliberately-blank probe value before it ever reaches the
    function under test. Mirrors test_capability_descriptor_set_emit._writes_back_plan."""
    deps = [dict(_DECLARED_DEP)] if identity is None else identity
    p = copy.deepcopy(_valid_plan())
    p["bundle_version"] = bundle_version
    p["foundation_doc_inputs"][IDENTITY_FIELD] = json.dumps(deps)
    if extra_fdi:
        p["foundation_doc_inputs"].update(extra_fdi)
    return validate_emission_plan(p, EP_CONTRACT)


def _emit(plan, staging):
    return generate_operator_system(
        plan, staging, REPO_ROOT, generator_version_override=plan.generator_version)


def _legacy_fixture(test_case, bundle_version=_SOURCE_VERSION):
    """Emit a real full writes-back system, then strip CAPABILITY_DESCRIPTORS_JSON
    from the in-memory capsule dict -- reproducing exactly what a v0.10.0..v0.13.1
    -era (pre-fix) capsule looked like on disk, without needing a frozen legacy
    fixture. Returns (staging_dir, manifest_dict, capsule_dict)."""
    td = tempfile.TemporaryDirectory()
    test_case.addCleanup(td.cleanup)
    staging = Path(td.name)
    plan = _writes_back_plan(bundle_version=bundle_version)
    _emit(plan, staging)
    manifest = json.loads((staging / ".wizard" / "manifest.json").read_text(encoding="utf-8"))
    capsule = json.loads((staging / REPLAY_CAPSULE_REL).read_text(encoding="utf-8"))
    test_case.assertIn(cdr.EMIT_FIELD, capsule["foundation_doc_inputs"],
                       "test premise: a fresh (post-fix) emit must carry the key so "
                       "stripping it below faithfully simulates the PRE-fix capsule")
    del capsule["foundation_doc_inputs"][cdr.EMIT_FIELD]
    return staging, manifest, capsule


# ============================================================================
# Part 1 -- upstream hydration
# ============================================================================

class HydrationFieldTests(unittest.TestCase):
    """agent_emitter.ensure_capability_descriptor_emit_field: the upstream hydration
    seam that runs before BOTH the descriptor emitter and build_replay_capsule."""

    def test_hydrates_when_absent_on_writes_back_plan(self):
        plan = _writes_back_plan()
        self.assertNotIn(cdr.EMIT_FIELD, plan.foundation_doc_inputs, "test premise")
        agent_emitter.ensure_capability_descriptor_emit_field(plan)
        self.assertIn(cdr.EMIT_FIELD, plan.foundation_doc_inputs)
        value = plan.foundation_doc_inputs[cdr.EMIT_FIELD]
        self.assertTrue(str(value).strip())
        # Matches the producer's own computation over the SAME identity (F4: mirrors
        # the emitter's precedence exactly).
        expected = cdr.render_initial_descriptor_set_json(plan.foundation_doc_inputs[IDENTITY_FIELD])
        self.assertEqual(value, expected)
        # F3: no trailing newline (the emitted template supplies the final one).
        self.assertFalse(value.endswith("\n"))

    def test_noop_on_non_writes_back_plan(self):
        plan = validate_emission_plan(copy.deepcopy(_valid_plan()), EP_CONTRACT)  # no boundary_output dep
        agent_emitter.ensure_capability_descriptor_emit_field(plan)
        self.assertNotIn(cdr.EMIT_FIELD, plan.foundation_doc_inputs,
                         "a read-only/no-dependency plan never carries a descriptor set")

    def test_existing_value_wins_idempotent(self):
        plan = _simple_writes_back_plan(extra_fdi={cdr.EMIT_FIELD: "[]"})
        agent_emitter.ensure_capability_descriptor_emit_field(plan)
        self.assertEqual(plan.foundation_doc_inputs[cdr.EMIT_FIELD], "[]",
                         "an explicitly-supplied value must win over hydration (idempotent)")

    def test_blank_value_is_treated_as_absent(self):
        plan = _simple_writes_back_plan(extra_fdi={cdr.EMIT_FIELD: "   "})
        agent_emitter.ensure_capability_descriptor_emit_field(plan)
        self.assertNotEqual(plan.foundation_doc_inputs[cdr.EMIT_FIELD].strip(), "",
                           "a whitespace-only existing value must not block hydration")

    def test_repeated_call_is_stable(self):
        plan = _writes_back_plan()
        agent_emitter.ensure_capability_descriptor_emit_field(plan)
        first = plan.foundation_doc_inputs[cdr.EMIT_FIELD]
        agent_emitter.ensure_capability_descriptor_emit_field(plan)
        self.assertEqual(plan.foundation_doc_inputs[cdr.EMIT_FIELD], first)


class EmittedBytesUnchangedByHydrationTests(unittest.TestCase):
    """Part 1's invariant: hydrating fdi upstream must NOT change the emitted
    security/capability_descriptors.json bytes -- same producer, same identity,
    just sourced from fdi (the emitter already prefers fdi[EMIT_FIELD] when present)."""

    def test_emitter_output_identical_with_and_without_hydration(self):
        plan_old = _writes_back_plan()  # OLD behavior: fdi lacks EMIT_FIELD
        plan_new = _writes_back_plan()  # NEW behavior: hydrated before the emitter runs
        agent_emitter.ensure_capability_descriptor_emit_field(plan_new)
        self.assertNotIn(cdr.EMIT_FIELD, plan_old.foundation_doc_inputs)
        self.assertIn(cdr.EMIT_FIELD, plan_new.foundation_doc_inputs)

        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            agent_emitter._emit_capability_descriptor_set(plan_old, Path(td1), REPO_ROOT)
            agent_emitter._emit_capability_descriptor_set(plan_new, Path(td2), REPO_ROOT)
            old_bytes = (Path(td1) / "security" / "capability_descriptors.json").read_bytes()
            new_bytes = (Path(td2) / "security" / "capability_descriptors.json").read_bytes()
        self.assertEqual(old_bytes, new_bytes,
                         "hydrating fdi upstream must not change the emitted bytes")

    def test_full_emit_bytes_match_independent_recomputation(self):
        # The full-orchestration proof: a real full emit's security/capability_descriptors.json
        # matches an INDEPENDENT recomputation from the producer over the same identity --
        # i.e. the hydration seam landing in the orchestrator changed nothing observable.
        with tempfile.TemporaryDirectory() as td:
            plan = _writes_back_plan()
            staging = Path(td)
            _emit(plan, staging)
            emitted = (staging / "security" / "capability_descriptors.json").read_bytes()
            identity_json = plan.foundation_doc_inputs[IDENTITY_FIELD]

        value = cdr.render_initial_descriptor_set_json(identity_json)
        template = (REPO_ROOT / "wizard" / "foundation-bundles" / _SOURCE_VERSION
                   / "templates" / "security" / "capability_descriptors.json").read_text(encoding="utf-8")
        expected, _ = _substitute_placeholders(
            template, {cdr.EMIT_FIELD: value}, template_name="capability_descriptors.json")
        self.assertEqual(emitted.decode("utf-8"), expected)


# ============================================================================
# Part 3(a) -- the central regression: fresh emit -> first upgrade must not refuse
# ============================================================================

class FreshEmitFirstUpgradeTests(unittest.TestCase):
    """A fresh FULL emit on a v0.10.0+ bundle (v0.13.1) must carry
    CAPABILITY_DESCRIPTORS_JSON in its capsule, and its FIRST apply_upgrade (to the
    latest bundle, v0.14.0) must NOT refuse at the descriptors conformance leg.
    Pre-fix this raised UpgradeApplyError citing the unresolved
    CAPABILITY_DESCRIPTORS_JSON placeholder."""

    def test_capsule_carries_descriptor_key(self):
        with tempfile.TemporaryDirectory() as td:
            plan = _writes_back_plan()
            staging = Path(td)
            _emit(plan, staging)
            capsule = json.loads((staging / REPLAY_CAPSULE_REL).read_text(encoding="utf-8"))
            fdi = capsule["foundation_doc_inputs"]
            self.assertIn(cdr.EMIT_FIELD, fdi)
            self.assertTrue(str(fdi[cdr.EMIT_FIELD]).strip())

    def test_first_upgrade_does_not_refuse_at_descriptors_leg(self):
        with tempfile.TemporaryDirectory() as td:
            plan = _writes_back_plan()
            staging = Path(td)
            _emit(plan, staging)

            # This fix makes no foundation-doc changes -- snapshot before, compare after.
            pre = {rel: (staging / rel).read_bytes() for rel in _FOUNDATION_DOCS}

            manifest_path = staging / ".wizard" / "manifest.json"
            manifest = load_operator_manifest(manifest_path)
            registry = load_registry(REGISTRY_PATH)
            try:
                result = apply_upgrade(
                    staging, _TARGET_VERSION, REPO_ROOT,
                    registry=registry, registry_path=REGISTRY_PATH,
                    manifest=manifest, manifest_path=manifest_path, ack=False,
                )
            except UpgradeApplyError as e:
                self.fail(f"apply_upgrade wrongly refused the first upgrade: {e}")

            self.assertIn(result.classification, (APPLY_RESULT_APPLIED, APPLY_RESULT_PARTIAL))
            for rel in _FOUNDATION_DOCS:
                self.assertEqual((staging / rel).read_bytes(), pre[rel],
                                 f"{rel} must stay byte-identical (this cut changes no foundation docs)")


# ============================================================================
# Part 2 -- read-side JIT backfill (repairs already-emitted legacy capsules)
# ============================================================================

class ReadSideBackfillTests(unittest.TestCase):
    """A legacy (pre-fix) v2 capsule missing CAPABILITY_DESCRIPTORS_JSON -- simulated
    by deleting the key after a real emit, exactly reproducing a v0.10.0..v0.13.1-era
    capsule -- must be repaired by the read-side JIT backfill, honestly verified by
    the EXISTING conformance base_hash check (never a silent pass, never a wrong
    render)."""

    def test_backfill_repairs_missing_key_and_conformance_passes(self):
        staging, manifest, capsule = _legacy_fixture(self)
        capsule_inputs = capsule["foundation_doc_inputs"]
        self.assertNotIn(cdr.EMIT_FIELD, capsule_inputs)

        _backfill_capsule_capability_descriptors(
            capsule, capsule_inputs, _SOURCE_VERSION, REPO_ROOT, manifest)
        self.assertIn(cdr.EMIT_FIELD, capsule_inputs, "backfill must inject the key")

        base_rendered = _render_version(_SOURCE_VERSION, capsule_inputs, REPO_ROOT)
        foundation_entries = _foundation_managed_entries(manifest, list(base_rendered.keys()))
        project_name = str(manifest.get("project_name", ""))
        try:
            _replay_conformance_check(
                _SOURCE_VERSION, capsule_inputs, REPO_ROOT, foundation_entries,
                capsule=capsule, manifest=manifest, project_name=project_name,
            )
        except UpgradeApplyError as e:
            self.fail(f"conformance wrongly refused after a correct backfill: {e}")

    def test_backfill_never_mutates_the_on_disk_capsule(self):
        staging, manifest, capsule = _legacy_fixture(self)
        capsule_inputs = capsule["foundation_doc_inputs"]
        on_disk_before = (staging / REPLAY_CAPSULE_REL).read_bytes()
        _backfill_capsule_capability_descriptors(
            capsule, capsule_inputs, _SOURCE_VERSION, REPO_ROOT, manifest)
        on_disk_after = (staging / REPLAY_CAPSULE_REL).read_bytes()
        self.assertEqual(on_disk_before, on_disk_after,
                         "the backfill is in-memory only -- never rewrite the on-disk capsule "
                         "(a migration write is a separate, deliberate flow)")

    def test_drifted_derivation_fails_closed_never_silent(self):
        # Simulate producer/engine drift (consult finding F5): the recorded manifest
        # base_hash for the descriptors file no longer matches what re-deriving from
        # the capsule's OWN identity reproduces. The backfill still ATTEMPTS the
        # injection (never silently skips it), but the pre-existing conformance gate
        # must refuse honestly -- no silent pass, no wrong render, no traceback.
        staging, manifest, capsule = _legacy_fixture(self)
        capsule_inputs = capsule["foundation_doc_inputs"]
        rel = "security/capability_descriptors.json"
        files_block = manifest.get("managed_files") or manifest.get("files") or {}
        self.assertIn(rel, files_block)
        files_block[rel] = dict(files_block[rel])
        files_block[rel]["base_hash"] = "sha256:" + ("0" * 64)  # deliberately wrong

        manifest_bytes_before = (staging / ".wizard" / "manifest.json").read_bytes()
        capsule_bytes_before = (staging / REPLAY_CAPSULE_REL).read_bytes()

        _backfill_capsule_capability_descriptors(
            capsule, capsule_inputs, _SOURCE_VERSION, REPO_ROOT, manifest)
        self.assertIn(cdr.EMIT_FIELD, capsule_inputs, "the backfill still attempts the injection")

        base_rendered = _render_version(_SOURCE_VERSION, capsule_inputs, REPO_ROOT)
        foundation_entries = _foundation_managed_entries(manifest, list(base_rendered.keys()))
        project_name = str(manifest.get("project_name", ""))
        with self.assertRaises(UpgradeApplyError) as ctx:
            _replay_conformance_check(
                _SOURCE_VERSION, capsule_inputs, REPO_ROOT, foundation_entries,
                capsule=capsule, manifest=manifest, project_name=project_name,
            )
        msg = str(ctx.exception)
        self.assertIn("replay-conformance gate FAILED", msg)
        self.assertIn(rel, msg)
        self.assertNotIn("Traceback", msg)
        # No disk write occurred as a side effect of the fail-closed path.
        self.assertEqual((staging / ".wizard" / "manifest.json").read_bytes(), manifest_bytes_before)
        self.assertEqual((staging / REPLAY_CAPSULE_REL).read_bytes(), capsule_bytes_before)


class BackfillGatingTests(unittest.TestCase):
    """The backfill must be gated precisely -- never fire outside its narrow lane."""

    def test_v1_capsule_never_backfilled(self):
        # A v1 (foundation-only) capsule has no operating block; the backfill must be
        # a no-op (never attempt operating-layer replay for a v1 capsule).
        capsule = {"schema_version": "replay-capsule-v1", "foundation_doc_inputs": {}}
        capsule_inputs = capsule["foundation_doc_inputs"]
        _backfill_capsule_capability_descriptors(
            capsule, capsule_inputs, _SOURCE_VERSION, REPO_ROOT, {"managed_files": {}})
        self.assertNotIn(cdr.EMIT_FIELD, capsule_inputs)

    def test_unmanaged_relpath_not_backfilled(self):
        # The manifest does not (yet) manage security/capability_descriptors.json ->
        # no backfill attempted (nothing recorded to conform against).
        staging, manifest, capsule = _legacy_fixture(self)
        capsule_inputs = capsule["foundation_doc_inputs"]
        rel = "security/capability_descriptors.json"
        files_block = manifest.get("managed_files") or manifest.get("files") or {}
        self.assertIn(rel, files_block)
        del files_block[rel]
        _backfill_capsule_capability_descriptors(
            capsule, capsule_inputs, _SOURCE_VERSION, REPO_ROOT, manifest)
        self.assertNotIn(cdr.EMIT_FIELD, capsule_inputs)

    def test_already_present_key_left_untouched(self):
        # A fresh (post-fix) capsule already carries the key -- the backfill must be a
        # true no-op (idempotent; never recompute/overwrite an existing value).
        _staging, manifest, capsule = _legacy_fixture(self)
        capsule_inputs = capsule["foundation_doc_inputs"]
        self.assertNotIn(cdr.EMIT_FIELD, capsule_inputs)  # _legacy_fixture stripped it in-memory
        capsule_inputs[cdr.EMIT_FIELD] = "sentinel-value"
        _backfill_capsule_capability_descriptors(
            capsule, capsule_inputs, _SOURCE_VERSION, REPO_ROOT, manifest)
        self.assertEqual(capsule_inputs[cdr.EMIT_FIELD], "sentinel-value")


if __name__ == "__main__":
    unittest.main()
