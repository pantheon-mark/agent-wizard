"""Tests for wizard/templates/claude_config/upgrade_notice.sh (stdlib unittest; pip-free).

Drives the script directly via subprocess with synthetic .wizard/manifest.json files
and a local fixture file as the registry source (via UPGRADE_NOTICE_REGISTRY_URL env
override pointing at a file:// URL).

Output contract (declarative-hook design): a SessionStart hook's stdout lands
in the model's session-start context, NOT in a user-visible message. Two prior designs
failed on live runs: operator-prose-with-paths was SUPPRESSED as "internal detail" by the
emitted system's "greet plainly / no file names" kickoff; an imperative model-relay
instruction with secrecy + an external command was CLASSIFIED AS A PROMPT-INJECTION ATTACK
by the system's own anti-injection/transparency operating-discipline. The fix: the hook
emits ONE minimal DECLARATIVE JSON line (data, not commands) when a newer version is
available; the "tell the operator" instruction lives in
durable config (the emitted CLAUDE.md startup section) which the model already trusts; the
trust boundary is the in-project upgrade tool, which re-validates against the real registry.
These tests pin the JSON contract + the absence of injection tells + fail-open silence; the
live estate-transcript read is the behavioral proof that the model now relays it plainly.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Repo root for resolving the script path.
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "wizard" / "templates" / "claude_config" / "upgrade_notice.sh"


def _run_script(project_dir: Path, env_overrides: dict) -> subprocess.CompletedProcess:
    """Run upgrade_notice.sh with the given project dir and env overrides."""
    env = {**os.environ, "HOME": str(project_dir), **env_overrides}
    # The script reads .wizard/manifest.json relative to its working dir.
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        cwd=str(project_dir),
        env=env,
    )


def _write_manifest(project_dir: Path, version: str) -> None:
    wizard_dir = project_dir / ".wizard"
    wizard_dir.mkdir(exist_ok=True)
    (wizard_dir / "manifest.json").write_text(
        json.dumps({"foundation_bundle_version": version}),
        encoding="utf-8",
    )


def _write_registry_fixture(registry_dir: Path, versions: list) -> Path:
    """Write a local registry JSON fixture. Returns the file path.

    Uses the SAME key the live public registry uses (`foundation_bundle_version`);
    a fixture keyed differently would let the script silently never fire against
    the real registry while the test passed (a false-green). The
    RegistryShapeGuardTest below pins this to the real registry on disk.
    """
    bundles = [{"foundation_bundle_version": v} for v in versions]
    registry = {"bundles": bundles}
    p = registry_dir / "foundation-bundles.json"
    p.write_text(json.dumps(registry), encoding="utf-8")
    return p


def _project_files(project_dir: Path) -> set:
    """Return the set of file paths inside project_dir, excluding Python bytecode
    caches that Python itself writes under Library/Caches when HOME is set to tmpdir."""
    result = set()
    for f in project_dir.rglob("*"):
        if not f.is_file():
            continue
        parts = f.parts
        if "__pycache__" in parts or f.suffix == ".pyc":
            continue
        if "Library" in parts and "Caches" in parts:
            continue
        result.add(str(f))
    return result


# Injection-signature tells the OUTPUT must never contain (the prior failure mode):
# imperative assistant instructions, secrecy language, executable commands, file paths.
_INJECTION_TELLS = (
    "do not show", "don't show", "do this", "instruction for the assistant",
    "tell the operator", "the operator cannot see", "quietly",
    "wizard_upgrade.py", "upgrade-plan", "python3 ", "--manifest-path", "/users/",
)


class UpgradeNoticeNewerAvailableTest(unittest.TestCase):
    """When a newer version is available, the hook emits ONE declarative JSON line."""

    def _output(self, td: str) -> str:
        project_dir = Path(td)
        _write_manifest(project_dir, "v0.6.0")
        registry_file = _write_registry_fixture(Path(td), ["v0.6.0", "v0.6.1"])
        result = _run_script(project_dir, {
            "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
        })
        self.assertEqual(result.returncode, 0,
                         f"unexpected exit code {result.returncode}; stderr: {result.stderr}")
        return result.stdout.strip()

    def test_stdout_is_a_sessionstart_additionalcontext_wrapper(self):
        """CRITICAL delivery contract: a SessionStart hook's stdout only reaches the model's
        context if it is plain text OR a JSON object with hookSpecificOutput.additionalContext.
        A BARE JSON object (no hookSpecificOutput) is parsed as a control object and SILENTLY
        DROPPED — it never reaches context. (Empirically reproduced: the model reported not
        seeing the notice.) So the hook MUST emit the hookSpecificOutput wrapper."""
        with tempfile.TemporaryDirectory() as td:
            output = self._output(td)
            try:
                top = json.loads(output)
            except json.JSONDecodeError as e:
                self.fail(f"stdout is not valid JSON: {e}; got: {output!r}")
            hso = top.get("hookSpecificOutput")
            self.assertIsInstance(hso, dict,
                                  f"stdout MUST carry hookSpecificOutput or it never reaches "
                                  f"context; got: {output!r}")
            self.assertEqual(hso.get("hookEventName"), "SessionStart",
                             f"hookEventName must be 'SessionStart'; got: {output!r}")
            self.assertTrue(isinstance(hso.get("additionalContext"), str) and hso["additionalContext"].strip(),
                            f"additionalContext must be a non-empty string; got: {output!r}")

    def test_additionalcontext_carries_the_declarative_upgrade_notice(self):
        """The injected additionalContext carries the declarative wizard_system_event object
        (the data the CLAUDE.md relay rule keys on) — tagged, with the versions."""
        with tempfile.TemporaryDirectory() as td:
            ac = json.loads(self._output(td))["hookSpecificOutput"]["additionalContext"]
            self.assertIn("wizard_system_event", ac,
                          f"additionalContext must carry the wizard_system_event tag; got: {ac!r}")
            # the embedded object must be parseable + correct
            inner = json.loads(ac[ac.index("{"):ac.rindex("}") + 1])
            self.assertEqual(inner.get("wizard_system_event"), "upgrade_notice")
            self.assertIs(inner.get("update_available"), True)
            self.assertEqual(inner.get("latest_version"), "v0.6.1")
            self.assertEqual(inner.get("current_version"), "v0.6.0")

    def test_output_is_pure_data_with_no_injection_tells(self):
        """The output must carry NONE of the prompt-injection tells that got the prior
        design flagged as an attack: no imperative assistant instructions, no secrecy,
        no executable command, no file paths."""
        with tempfile.TemporaryDirectory() as td:
            lower = self._output(td).lower()
            present = [t for t in _INJECTION_TELLS if t in lower]
            self.assertEqual(present, [],
                             f"output contains injection-signature tells {present}; "
                             f"it must be pure declarative data")


class UpgradeNoticeCurrentTest(unittest.TestCase):
    """Script exits 0 silently when the local version is current or ahead."""

    def test_notice_silent_when_current(self):
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_manifest(project_dir, "v0.6.0")
            registry_file = _write_registry_fixture(Path(td), ["v0.6.0"])
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
            })
            self.assertEqual(result.returncode, 0,
                             f"unexpected exit code {result.returncode}; stderr: {result.stderr}")
            self.assertEqual(result.stdout.strip(), "",
                             f"should be silent when current; got: {result.stdout!r}")

    def test_notice_silent_when_local_is_newer(self):
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_manifest(project_dir, "v0.6.1")
            registry_file = _write_registry_fixture(Path(td), ["v0.6.0"])
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
            })
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "",
                             f"should be silent when local is newer; got: {result.stdout!r}")


class UpgradeNoticeOfflineTest(unittest.TestCase):
    """Script exits 0 silently when the network is unavailable (fail-open)."""

    def test_notice_graceful_offline(self):
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_manifest(project_dir, "v0.6.0")
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": "http://127.0.0.1:19999/unreachable.json",
            })
            self.assertEqual(result.returncode, 0,
                             f"script should exit 0 on network failure; got {result.returncode}. "
                             f"stderr: {result.stderr}")
            self.assertEqual(result.stdout.strip(), "",
                             f"script should print nothing on failure; got: {result.stdout!r}")
            non_manifest = [
                p for p in _project_files(project_dir) if not p.endswith("manifest.json")
            ]
            self.assertEqual(non_manifest, [],
                             f"script wrote unexpected files: {non_manifest}")


class UpgradeNoticeMissingManifestTest(unittest.TestCase):
    """Script exits 0 silently when .wizard/manifest.json is absent or lacks the version."""

    def test_graceful_when_no_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": "http://127.0.0.1:19999/unreachable.json",
            })
            self.assertEqual(result.returncode, 0,
                             f"should exit 0 when manifest absent; stderr: {result.stderr}")
            self.assertEqual(result.stdout.strip(), "")

    def test_graceful_when_manifest_has_no_version_field(self):
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            wizard_dir = project_dir / ".wizard"
            wizard_dir.mkdir()
            (wizard_dir / "manifest.json").write_text(
                json.dumps({"other_field": "value"}), encoding="utf-8"
            )
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": "http://127.0.0.1:19999/unreachable.json",
            })
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), "")


class UpgradeNoticeReadOnlyTest(unittest.TestCase):
    """Script never writes files and never eval's fetched content."""

    def test_notice_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_manifest(project_dir, "v0.6.0")
            registry_file = _write_registry_fixture(Path(td), ["v0.6.0", "v0.6.1"])
            files_before = {p: Path(p).read_bytes() for p in _project_files(project_dir)}
            _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": f"file://{registry_file}",
            })
            files_after = _project_files(project_dir)
            new_files = files_after - set(files_before.keys())
            self.assertEqual(new_files, set(), f"script wrote new files: {new_files}")
            for path_str, before_bytes in files_before.items():
                p = Path(path_str)
                if not p.is_file():
                    continue
                self.assertEqual(before_bytes, p.read_bytes(),
                                 f"script modified file: {path_str}")

    def test_script_contains_no_eval_of_fetched_content(self):
        script_text = SCRIPT_PATH.read_text(encoding="utf-8")
        import re
        dangerous_eval = re.search(r'\beval\s+\$\(?.*?(?:curl|wget|fetch|registry)\b',
                                   script_text, re.IGNORECASE | re.DOTALL)
        self.assertIsNone(dangerous_eval,
                          "script appears to eval fetched content — security issue")


class UpgradeNoticeScriptSyntaxTest(unittest.TestCase):
    """The script must pass bash -n (syntax check) cleanly."""

    def test_bash_syntax_clean(self):
        result = subprocess.run(
            ["bash", "-n", str(SCRIPT_PATH)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0,
                         f"bash -n failed on upgrade_notice.sh: {result.stderr}")


class RegistryShapeGuardTest(unittest.TestCase):
    """Pin the notice to the REAL on-disk registry shape, not a hand-built fixture.

    The notice reads each bundle's version from `foundation_bundle_version` (the live
    registry key). If the script ever reverts to a different key, this test fails
    because the notice would silently never fire against the real registry — a
    false-green that a same-shape mock fixture cannot catch.
    """

    REAL_REGISTRY = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"

    def test_real_registry_uses_expected_version_key(self):
        reg = json.loads(self.REAL_REGISTRY.read_text(encoding="utf-8"))
        bundles = reg.get("bundles") or []
        self.assertTrue(bundles, "real registry has no bundles")
        for b in bundles:
            self.assertIn("foundation_bundle_version", b,
                          "real registry bundle entry lacks foundation_bundle_version — "
                          "the notice's version-key read must match this shape")

    def test_notice_fires_against_the_real_registry(self):
        """Run the notice against the real registry with a below-all local version; it must
        emit the hookSpecificOutput wrapper whose additionalContext carries the upgrade notice
        (proves the real key is read AND the output reaches context)."""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            _write_manifest(project_dir, "v0.0.1")
            result = _run_script(project_dir, {
                "UPGRADE_NOTICE_REGISTRY_URL": "file://" + str(self.REAL_REGISTRY),
            })
            self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
            hso = json.loads(result.stdout.strip()).get("hookSpecificOutput", {})
            self.assertEqual(hso.get("hookEventName"), "SessionStart",
                             f"notice did not fire against the real registry (key mismatch?); "
                             f"stdout: {result.stdout!r}")
            ac = hso.get("additionalContext", "")
            self.assertIn("wizard_system_event", ac)
            inner = json.loads(ac[ac.index("{"):ac.rindex("}") + 1])
            self.assertIs(inner.get("update_available"), True)
            self.assertTrue(inner.get("latest_version"),
                            f"notice must name a latest_version; got: {ac!r}")


class DurableRelayInstructionContractTest(unittest.TestCase):
    """The model relays the notice only if a DURABLE instruction it trusts tells it to.
    That instruction lives in the emitted CLAUDE.md startup section (read first at every
    session start). Pin it here so it can never silently drop — without it, the declarative
    JSON sits in context with no guidance and is suppressed as 'internal detail' (failure 1).
    """

    # The bundle copy that the upgrade DELIVERS (and that fresh emits source from).
    BUNDLE_CLAUDE_MD = (REPO_ROOT / "wizard" / "foundation-bundles" / "v0.6.0"
                        / "templates" / "root" / "CLAUDE.md")

    def test_claude_md_carries_the_upgrade_notice_relay_rule(self):
        text = self.BUNDLE_CLAUDE_MD.read_text(encoding="utf-8")
        low = text.lower()
        # references the declarative event tag the hook emits
        self.assertIn("wizard_system_event", text,
                      "CLAUDE.md must reference the wizard_system_event upgrade-notice tag")
        # instructs the model to TELL the operator
        self.assertTrue(any(p in low for p in ("tell the operator", "let the operator know",
                                               "tell them")),
                        "CLAUDE.md must instruct relaying the notice to the operator")
        # advisory-only / never auto-act containment
        self.assertTrue(any(p in low for p in ("advisory", "never run", "never apply",
                                               "do not run", "do not apply")),
                        "CLAUDE.md must scope the notice as advisory / never auto-act")
        # routes review through the in-project upgrade process
        self.assertIn("upgrading.md", low,
                      "CLAUDE.md must route review through the in-project upgrade process")


if __name__ == "__main__":
    unittest.main()
