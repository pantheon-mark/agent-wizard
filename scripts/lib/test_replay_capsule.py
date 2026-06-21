"""Tests for the replay-capsule emitter (stdlib unittest).

Covers: capsule shape + provenance fields; foundation_doc_inputs round-trip;
fail-closed secret scan across each planted-secret class (anti-overfit: rule-level
detectors, divergent inputs) + a realistic clean-inputs fixture (no false positive on
prose); control_files inventory includes the capsule + managed_files excludes it;
determinism (same plan -> byte-identical capsule).
"""

import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import replay_capsule as rc  # noqa: E402
from replay_capsule import (  # noqa: E402
    CAPSULE_SCHEMA_VERSION, CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY,
    REPLAY_CAPSULE_REL, ReplayCapsuleError,
    build_replay_capsule, emit_replay_capsule, scan_inputs_for_secrets,
)
from upgrade import CANONICALIZATION_VERSION, HASH_ALGORITHM  # noqa: E402

# Reuse the assembled-plan harness the parity tests use, so the capsule is exercised
# against a real EmissionPlan (not a hand-built stub).
from test_parity import _plan, REPO_ROOT  # noqa: E402


# A realistic clean foundation_doc_inputs fixture — normal non-technical business
# answers, including long prose, hyphenated phrases, dates, and a long field name.
# NONE of this should trip the secret scan.
_CLEAN_INPUTS = {
    "PROJECT_NAME": "Estate Settlement Helper",
    "PROJECT_PURPOSE": (
        "Help me manage everything involved in settling my dad's estate as "
        "co-executor with my mom, so nothing falls through the cracks, including "
        "researching the best way to proceed with probate and account transfers."
    ),
    "VISION_CONSTRAINTS": "Must keep all financial records organized; no missed deadlines.",
    "AUTONOMY_LEVEL": "2",
    "HITL_MAP_ROWS": "Any payment over $500 requires my explicit approval before it is sent.",
    "A_VERY_LONG_DESCRIPTIVE_FIELD_NAME_THAT_IS_NOT_A_SECRET": (
        "This is a perfectly ordinary sentence that happens to be fairly long, with "
        "plenty of spaces between the words so it reads like normal business prose."
    ),
    "CONTACT_NOTE": "Reach the attorney, Pat Morgan, at the firm's main line during business hours.",
    "NESTED": {"goal": "keep mom informed weekly", "tags": ["estate", "probate", "year-2026"]},
}

# Each planted-secret class as a (label, value) pair — anti-overfit: the detectors are
# rule-level, so a fresh token of each shape must still be caught.
#
# NOTE: every token-shaped value is ASSEMBLED FROM FRAGMENTS at runtime (e.g. "sk-" + "...").
# The runtime string is byte-identical to a real token shape (so the guard under test still
# matches it), but the SOURCE TEXT contains no contiguous detectable literal. This keeps these
# fixtures from tripping upstream push-protection / secret scanners when this file ships in the
# public wizard/ subtree — the very tool this guard mimics would otherwise block the publish.
_PLANTED_SECRETS = [
    ("openai_sk", "sk-" + "abc123DEF456ghi789JKL012mno345"),
    ("github_pat", "ghp" + "_ABCdef0123456789ABCdef0123456789ABCD"),
    ("aws_akia", "AKIA" + "IOSFODNN7EXAMPLE"),
    ("private_key", "-----BEGIN" + " RSA PRIVATE KEY-----\nMIIEowIB...\n-----END RSA PRIVATE KEY-----"),
    ("slack_token", "xox" + "b-1234567890-0987654321-abcdEFGHijklMNOPqrstUVWX"),
    ("password_assignment", "the db " + "password=hunter2supersecret is in the config"),
    ("token_assignment", "auth_" + "token: eyJhbGciOiJ9verylongvaluehere123456"),
    ("apikey_assignment", "api_" + "key=ZK39ksdLLqmZ02kfPwoeUUDJ"),
    ("high_entropy_hex", "9f8e7d6c5b4a3928" + "1706f5e4d3c2b1a09f8e7d6c5b4a3928"),
    ("high_entropy_b64", "aGVsbG9Xb3JsZF9UaGlz" + "SXNBVmVyeUxvbmdSYW5kb21Ub2tlbg=="),
]


class CapsuleShapeTests(unittest.TestCase):
    def test_capsule_shape_and_provenance(self):
        plan = _plan()
        # Without a build_repo_root the capsule carries no operating block (v1 shape).
        doc = build_replay_capsule(plan)
        self.assertEqual(doc["schema_version"], CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY)
        self.assertNotIn("operating", doc)
        self.assertEqual(doc["foundation_bundle_version"], plan.bundle_version)
        self.assertEqual(doc["generator_version"], plan.generator_version)
        self.assertEqual(doc["system_shape"], plan.system_shape)
        self.assertEqual(doc["foundation_only_mode"], plan.foundation_only_mode)
        self.assertEqual(doc["canonicalization_version"], CANONICALIZATION_VERSION)
        self.assertEqual(doc["hash_algorithm"], HASH_ALGORITHM)

    def test_generator_version_is_40_sha_from_plan(self):
        plan = _plan()
        doc = build_replay_capsule(plan)
        # Provenance reused from the plan (same source the manifest uses), not re-derived.
        self.assertEqual(len(doc["generator_version"]), 40)
        self.assertEqual(doc["generator_version"], plan.generator_version)

    def test_foundation_doc_inputs_round_trip(self):
        plan = _plan()
        doc = build_replay_capsule(plan)
        self.assertEqual(doc["foundation_doc_inputs"], dict(plan.foundation_doc_inputs))
        # round-trips through JSON byte-for-byte at the value level
        reloaded = json.loads(json.dumps(doc))
        self.assertEqual(reloaded["foundation_doc_inputs"], dict(plan.foundation_doc_inputs))

    def test_foundation_only_provenance(self):
        plan = _plan(foundation_only=True)
        doc = build_replay_capsule(plan)
        self.assertTrue(doc["foundation_only_mode"])


class SecretScanTests(unittest.TestCase):
    def test_clean_inputs_pass(self):
        # Must NOT false-positive on ordinary business prose / long field names.
        try:
            scan_inputs_for_secrets(_CLEAN_INPUTS)
        except ReplayCapsuleError as e:  # pragma: no cover
            self.fail(f"clean inputs wrongly flagged as secret: {e}")

    def test_real_plan_inputs_clean(self):
        # The assembled estate-pilot-shaped plan inputs must be scan-clean.
        plan = _plan()
        scan_inputs_for_secrets(plan.foundation_doc_inputs)  # no raise

    def test_each_planted_secret_class_fails(self):
        for label, value in _PLANTED_SECRETS:
            with self.subTest(secret_class=label):
                inputs = dict(_CLEAN_INPUTS)
                inputs[f"FIELD_{label}"] = value
                with self.assertRaises(ReplayCapsuleError) as ctx:
                    scan_inputs_for_secrets(inputs)
                msg = str(ctx.exception)
                # message names the KEY, not the value, and points at .env
                self.assertIn(f"FIELD_{label}", msg)
                self.assertNotIn(value, msg)
                self.assertIn(".env", msg)

    def test_secret_in_nested_container_caught(self):
        inputs = dict(_CLEAN_INPUTS)
        inputs["NESTED_SECRET"] = {"creds": ["sk-" + "abc123DEF456ghi789JKL012mno345"]}
        with self.assertRaises(ReplayCapsuleError):
            scan_inputs_for_secrets(inputs)

    def test_emit_refuses_when_secret_present(self):
        plan = _plan()
        bad_inputs = dict(plan.foundation_doc_inputs)
        bad_inputs["LEAKED_KEY"] = "ghp" + "_ABCdef0123456789ABCdef0123456789ABCD"
        bad_plan = replace(plan, foundation_doc_inputs=bad_inputs)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ReplayCapsuleError):
                emit_replay_capsule(bad_plan, Path(td), REPO_ROOT)
            # fail-closed: nothing written
            self.assertFalse((Path(td) / REPLAY_CAPSULE_REL).exists())

    def test_low_cardinality_long_run_not_flagged(self):
        # A long run of few distinct chars (e.g. a separator/underline) is NOT a secret.
        try:
            scan_inputs_for_secrets({"DIVIDER": "=" * 60, "REPEAT": "abcabcabc" * 8})
        except ReplayCapsuleError as e:  # pragma: no cover
            self.fail(f"low-cardinality run wrongly flagged: {e}")


class EmitAndManifestTests(unittest.TestCase):
    def test_emit_writes_capsule_well_formed(self):
        plan = _plan()
        with tempfile.TemporaryDirectory() as td:
            dest = emit_replay_capsule(plan, Path(td), REPO_ROOT)
            self.assertTrue(dest.exists())
            text = dest.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            doc = json.loads(text)
            self.assertEqual(doc["schema_version"], CAPSULE_SCHEMA_VERSION)

    def test_determinism_byte_identical(self):
        plan = _plan()
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            a = emit_replay_capsule(plan, Path(td1), REPO_ROOT).read_bytes()
            b = emit_replay_capsule(plan, Path(td2), REPO_ROOT).read_bytes()
            self.assertEqual(a, b)

    def test_control_files_includes_capsule_managed_excludes_it(self):
        # Full emit: the manifest must inventory the capsule under control_files and
        # NOT hash it into managed_files (same handling as the other .wizard control files).
        from operator_system_emitter import generate_operator_system
        from upgrade_scaffold_emitter import MANIFEST_REL
        plan = _plan()
        with tempfile.TemporaryDirectory() as td:
            generate_operator_system(plan, Path(td), REPO_ROOT,
                                     generator_version_override=plan.generator_version)
            self.assertTrue((Path(td) / REPLAY_CAPSULE_REL).exists())
            manifest = json.loads((Path(td) / MANIFEST_REL).read_text(encoding="utf-8"))
            self.assertIn(REPLAY_CAPSULE_REL, manifest["control_files"])
            self.assertNotIn(REPLAY_CAPSULE_REL, manifest["managed_files"])

    def test_emitted_capsule_is_gitignored(self):
        from operator_system_emitter import generate_operator_system
        plan = _plan()
        with tempfile.TemporaryDirectory() as td:
            generate_operator_system(plan, Path(td), REPO_ROOT,
                                     generator_version_override=plan.generator_version)
            gitignore = (Path(td) / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(REPLAY_CAPSULE_REL, gitignore)


class CapsuleV2OperatingBlockTests(unittest.TestCase):
    """The v2 durability proof: the operating block carries enough resolved input to
    re-render every `delivery:wizard render_kind:render` operating-layer file byte-identically."""

    def _wizard_render_entries(self):
        import json as _json
        contract_path = (REPO_ROOT / "wizard" / "foundation-bundles" / "v0.6.0"
                         / "system-artifacts.json")
        contract = _json.loads(contract_path.read_text(encoding="utf-8"))
        return [e for e in contract["artifacts"]
                if e.get("delivery") == "wizard" and e.get("render_kind") == "render"]

    def _target_derived_scaffold_map(self, plan):
        """The substitution values a re-render legitimately RE-DERIVES from the target
        bundle (NOT read from the capsule): the bundle-shipped deterministic scaffold
        defaults, the corpus/autonomy-derived blocks, and the resolved model strings.
        Persisted values are deliberately excluded here — they come from the capsule."""
        from scaffold_emitter import _default_scaffold_inputs
        from corpus_emitter import render_claude_md_block
        from corpus_loader import load_corpus_pack
        from authority_profile import autonomous_actions_summary
        records = load_corpus_pack()
        m = dict(_default_scaffold_inputs())
        m["INHERITED_OPERATING_PRINCIPLES"] = render_claude_md_block(plan, records)
        m["AUTONOMOUS_ACTIONS"] = autonomous_actions_summary(
            plan.foundation_doc_inputs.get("AUTONOMY_LEVEL", "1"))
        m["MODEL_HIGH"] = plan.model_tiers["high"]
        m["MODEL_STANDARD"] = plan.model_tiers["standard"]
        m["MODEL_FAST"] = plan.model_tiers["fast"]
        # quality/rules_library.md (the corpus single-home) is the one wizard-render file
        # not emitted by the scaffold/agent layer; its body is corpus-derived (target bundle),
        # so RULES_LIBRARY_ENTRIES is re-derived here, not carried in the capsule.
        from corpus_emitter import _resolved_records, render_rules_library_entries, INSTALLED_DATE_KEY, DEFAULT_INSTALLED_MARKER
        resolved = _resolved_records(plan, records)
        created = str((plan.foundation_doc_inputs or {}).get(INSTALLED_DATE_KEY, DEFAULT_INSTALLED_MARKER))
        m["RULES_LIBRARY_ENTRIES"] = render_rules_library_entries(resolved, created)
        return m

    def test_capsule_v2_reproduces_render_kind_operating_files(self):
        from operator_system_emitter import generate_operator_system
        from generator import _substitute_placeholders
        from bundle_templates import bundle_template_path
        from corpus_emitter import inject_target_hooks
        plan = _plan()
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as rd:
            generate_operator_system(plan, Path(td), REPO_ROOT,
                                     generator_version_override=plan.generator_version)
            staging = Path(td)
            rerender = Path(rd)
            capsule = json.loads((staging / REPLAY_CAPSULE_REL).read_text(encoding="utf-8"))
            self.assertEqual(capsule["schema_version"], CAPSULE_SCHEMA_VERSION)
            op = capsule["operating"]
            fdi = capsule["foundation_doc_inputs"]
            scaffold_resolved = op["resolved_scaffold_inputs"]
            by_relpath = op["by_relpath"]

            # The target-derived scaffold pieces (re-derived from the target bundle, NOT
            # the capsule) — used ONLY for scaffold/root render files.
            target_derived = self._target_derived_scaffold_map(plan)

            # The full set of wizard-render files to re-render: the contract's scaffold/root/
            # foundation render entries that this plan actually emitted, PLUS every agent-layer
            # file the capsule's by_relpath carries (the test plan's agent roster differs from
            # the contract's frozen roster, so the agent files come from by_relpath, not the
            # static contract list).
            contract_render = {e["relpath"] for e in self._wizard_render_entries()}
            all_relpaths = sorted((contract_render & {
                str(p.relative_to(staging)) for p in staging.rglob("*") if p.is_file()
            }) | set(by_relpath))

            # Re-render each FROM (capsule inputs + bundle templates + target-derived) into a
            # fresh tree, substituting placeholders only.
            bundle_templates_root = (REPO_ROOT / "wizard" / "foundation-bundles"
                                     / "v0.6.0" / "templates")

            def _template_for(relpath):
                # Agent-layer relpaths use the SHARED templates (the contract's frozen roster
                # differs from this plan's roster, so resolve by shape, not contract lookup).
                if relpath == "agents/prompts/orchestrator_prompt.md":
                    return bundle_templates_root / "agents/orchestrator_prompt.md"
                if relpath == "agents/prompts/qa_agent_prompt.md":
                    return bundle_templates_root / "agents/qa_agent_prompt.md"
                if relpath == "agents/cron/cron_config.md":
                    return bundle_templates_root / "agents/cron_config.md"
                if relpath.startswith("agents/prompts/") and relpath.endswith("_prompt.md"):
                    return bundle_templates_root / "agents/agent_prompt_template.md"
                if relpath.startswith("agents/scripts/") and relpath.endswith(".sh"):
                    return bundle_templates_root / "scripts/agent_invocation_template.sh"
                return bundle_template_path("v0.6.0", relpath, REPO_ROOT)

            relpaths = []
            for relpath in all_relpaths:
                if relpath in by_relpath:
                    # Agent-layer file: the resolved dict is fully self-contained.
                    inputs = dict(by_relpath[relpath])
                else:
                    # Scaffold/root/foundation render file: target-derived defaults,
                    # overlaid with capsule-persisted values (fdi + scaffold-resolved).
                    inputs = dict(target_derived)
                    inputs.update(fdi)
                    inputs.update(scaffold_resolved)
                template_text = _template_for(relpath).read_text(encoding="utf-8")
                rendered, _ = _substitute_placeholders(
                    template_text, inputs, template_name=relpath)
                out = rerender / relpath
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(rendered, encoding="utf-8")
                relpaths.append(relpath)

            # Re-apply the bundle's deterministic post-render hook injection (the hooks
            # come from the target bundle's corpus, not from operator input) — exactly the
            # transform the emitter runs at step 5. This is part of "re-render from the
            # target bundle", and the capsule needs to carry nothing extra for it.
            inject_target_hooks(plan, rerender)

            # Byte-identity proof across every re-rendered wizard-render file.
            for relpath in relpaths:
                self.assertEqual(
                    (rerender / relpath).read_text(encoding="utf-8"),
                    (staging / relpath).read_text(encoding="utf-8"),
                    f"re-render mismatch for {relpath}")
            # Sanity: we actually exercised the scaffold + agent render files.
            self.assertGreaterEqual(len(relpaths), 25)
            self.assertIn("CLAUDE.md", relpaths)
            self.assertIn("operating_discipline.md", relpaths)
            self.assertIn("project_instructions.md", relpaths)
            self.assertIn("agents/prompts/orchestrator_prompt.md", relpaths)
            # The test plan's actual specialist agent file (roster differs from the contract).
            self.assertIn("agents/prompts/researcher_prompt.md", relpaths)
            self.assertIn("agents/scripts/researcher.sh", relpaths)

    def test_capsule_v2_deterministic(self):
        plan = _plan()
        a = build_replay_capsule(plan, REPO_ROOT)
        b = build_replay_capsule(plan, REPO_ROOT)
        self.assertEqual(
            json.dumps(a, indent=2, sort_keys=True),
            json.dumps(b, indent=2, sort_keys=True))
        # And the emitted bytes are identical across two staging dirs.
        with tempfile.TemporaryDirectory() as td1, tempfile.TemporaryDirectory() as td2:
            x = emit_replay_capsule(plan, Path(td1), REPO_ROOT).read_bytes()
            y = emit_replay_capsule(plan, Path(td2), REPO_ROOT).read_bytes()
            self.assertEqual(x, y)

    def test_capsule_v2_secret_scan_covers_operating_inputs(self):
        plan = _plan()
        # Plant a credential-shaped value into a PERSISTED scaffold input (lands in the
        # operating block's resolved_scaffold_inputs, not foundation_doc_inputs) and prove
        # the operating-aware scan fires, naming the key (never the value).
        secret = "ghp" + "_ABCdef0123456789ABCdef0123456789ABCD"
        doc = build_replay_capsule(plan, REPO_ROOT)
        self.assertIn("AUTOMATION_CREDIT_POOL", doc["operating"]["resolved_scaffold_inputs"])
        doc["operating"]["resolved_scaffold_inputs"]["AUTOMATION_CREDIT_POOL"] = secret
        with self.assertRaises(ReplayCapsuleError) as ctx:
            scan_inputs_for_secrets(plan.foundation_doc_inputs, doc["operating"])
        msg = str(ctx.exception)
        self.assertIn("AUTOMATION_CREDIT_POOL", msg)
        self.assertNotIn(secret, msg)

    def test_capsule_v2_secret_scan_covers_agent_inputs(self):
        plan = _plan()
        doc = build_replay_capsule(plan, REPO_ROOT)
        # Plant into an agent's resolved dict.
        relpath = next(iter(doc["operating"]["by_relpath"]))
        secret = "sk-" + "abc123DEF456ghi789JKL012mno345"
        doc["operating"]["by_relpath"][relpath]["OUTPUT_FORMAT_SPECIFICATION"] = secret
        with self.assertRaises(ReplayCapsuleError) as ctx:
            scan_inputs_for_secrets(plan.foundation_doc_inputs, doc["operating"])
        msg = str(ctx.exception)
        self.assertIn(relpath, msg)
        self.assertNotIn(secret, msg)

    def test_foundation_only_emit_capsule_has_no_operating_block(self):
        plan = _plan(foundation_only=True)
        doc = build_replay_capsule(plan, REPO_ROOT)
        self.assertEqual(doc["schema_version"], CAPSULE_SCHEMA_VERSION_FOUNDATION_ONLY)
        self.assertNotIn("operating", doc)


if __name__ == "__main__":
    unittest.main()
