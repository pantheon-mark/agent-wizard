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
    CAPSULE_SCHEMA_VERSION, REPLAY_CAPSULE_REL, ReplayCapsuleError,
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
        doc = build_replay_capsule(plan)
        self.assertEqual(doc["schema_version"], CAPSULE_SCHEMA_VERSION)
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


if __name__ == "__main__":
    unittest.main()
