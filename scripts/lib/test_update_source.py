"""Tests for the durable, read-only update-source reference (.wizard/update-source.json).

Covers: the renderer/loader round-trip; required-field + HTTPS + internal-consistency
fail-closed validation; the deny-set membership (the reference is read-only to the
assistant in the emitted .claude/settings.json, same anti-self-bypass pattern as
.claude/**); and the system-artifacts contract carries it as a clobber-safe managed file.

Stdlib unittest; pip-install-free.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from update_source import (  # noqa: E402
    UPDATE_SOURCE_REL,
    UPDATE_SOURCE_SCHEMA_VERSION,
    CANONICAL_REPO_OWNER,
    CANONICAL_REPO_NAME,
    CANONICAL_HTTPS_URL,
    LAST_KNOWN_GOOD_PLACEHOLDER,
    UpdateSourceError,
    emit_update_source,
    load_update_source,
    render_update_source,
    render_update_source_json,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLE_VERSION = "v0.6.1"
BUNDLE_DIR = REPO_ROOT / "wizard" / "foundation-bundles" / BUNDLE_VERSION


class UpdateSourceRenderTests(unittest.TestCase):
    def test_render_carries_pinned_origin_fields(self):
        doc = render_update_source()
        self.assertEqual(doc["schema_version"], UPDATE_SOURCE_SCHEMA_VERSION)
        self.assertEqual(doc["repo_owner"], CANONICAL_REPO_OWNER)
        self.assertEqual(doc["repo_name"], CANONICAL_REPO_NAME)
        self.assertEqual(doc["https_url"], CANONICAL_HTTPS_URL)
        self.assertTrue(doc["https_url"].startswith("https://"))
        self.assertIn("raw_base_url", doc)
        self.assertEqual(doc["branch"], "main")
        self.assertEqual(doc["last_known_good_commit"], LAST_KNOWN_GOOD_PLACEHOLDER)
        self.assertIn("toolkit_install_convention", doc)

    def test_render_with_known_commit(self):
        doc = render_update_source(last_known_good_commit="abc1234")
        self.assertEqual(doc["last_known_good_commit"], "abc1234")

    def test_render_json_is_deterministic(self):
        a = render_update_source_json()
        b = render_update_source_json()
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("\n"))
        # sorted keys
        self.assertEqual(json.loads(a)["repo_owner"], CANONICAL_REPO_OWNER)


class UpdateSourceEmitLoadTests(unittest.TestCase):
    def test_emit_then_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d)
            written = emit_update_source(staging)
            self.assertEqual(written, staging / UPDATE_SOURCE_REL)
            self.assertTrue(written.is_file())
            loaded = load_update_source(staging)
            self.assertEqual(loaded["repo_owner"], CANONICAL_REPO_OWNER)
            self.assertEqual(loaded["https_url"], CANONICAL_HTTPS_URL)

    def test_load_missing_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(UpdateSourceError):
                load_update_source(Path(d))

    def test_load_malformed_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d)
            (staging / ".wizard").mkdir()
            (staging / UPDATE_SOURCE_REL).write_text("{ not json", encoding="utf-8")
            with self.assertRaises(UpdateSourceError):
                load_update_source(staging)

    def test_load_non_https_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d)
            (staging / ".wizard").mkdir()
            doc = render_update_source()
            doc["https_url"] = "http://github.com/pantheon-mark/agent-wizard.git"
            (staging / UPDATE_SOURCE_REL).write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(UpdateSourceError):
                load_update_source(staging)

    def test_load_inconsistent_owner_repo_fails_closed(self):
        # An https_url that does not match the recorded owner/repo is treated as tampered.
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d)
            (staging / ".wizard").mkdir()
            doc = render_update_source()
            doc["https_url"] = "https://github.com/attacker/evil.git"
            (staging / UPDATE_SOURCE_REL).write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(UpdateSourceError):
                load_update_source(staging)

    def test_load_missing_required_field_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            staging = Path(d)
            (staging / ".wizard").mkdir()
            doc = render_update_source()
            del doc["repo_owner"]
            (staging / UPDATE_SOURCE_REL).write_text(json.dumps(doc), encoding="utf-8")
            with self.assertRaises(UpdateSourceError):
                load_update_source(staging)


class UpdateSourceDenySetTests(unittest.TestCase):
    """The reference must be read-only to the assistant: in the emitted settings.json
    permissions.deny set (same anti-self-bypass pattern as .claude/**)."""

    def _settings(self, base: Path) -> dict:
        return json.loads(
            (base / "templates" / "claude_config" / "settings.json").read_text(encoding="utf-8")
        )

    def test_build_template_settings_deny_update_source(self):
        settings = json.loads(
            (REPO_ROOT / "wizard" / "templates" / "claude_config" / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        deny = settings["permissions"]["deny"]
        self.assertIn(f"Edit({UPDATE_SOURCE_REL})", deny)
        self.assertIn(f"Write({UPDATE_SOURCE_REL})", deny)

    def test_bundle_template_settings_deny_update_source(self):
        settings = self._settings(BUNDLE_DIR)
        deny = settings["permissions"]["deny"]
        self.assertIn(f"Edit({UPDATE_SOURCE_REL})", deny)
        self.assertIn(f"Write({UPDATE_SOURCE_REL})", deny)


class UpdateSourceContractTests(unittest.TestCase):
    """The v0.6.1 system-artifacts contract carries the reference as a clobber-safe
    managed file (control_plane_refresh, source=control_plane, no template_path)."""

    def test_contract_carries_update_source_clobber_safe(self):
        contract = json.loads((BUNDLE_DIR / "system-artifacts.json").read_text(encoding="utf-8"))
        by_rel = {a["relpath"]: a for a in contract["artifacts"]}
        self.assertIn(UPDATE_SOURCE_REL, by_rel)
        entry = by_rel[UPDATE_SOURCE_REL]
        # Clobber-safe: NOT warn_on_drift (a single global --ack must not clobber this
        # safety-critical config). control_plane_refresh or operator_review accepted.
        self.assertIn(entry["merge_strategy"], {"control_plane_refresh", "operator_review"})
        self.assertNotEqual(entry["merge_strategy"], "warn_on_drift")
        self.assertEqual(entry["source"], "control_plane")
        self.assertNotIn("template_path", entry)


if __name__ == "__main__":
    unittest.main()
