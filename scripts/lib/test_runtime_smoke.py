"""Runtime mock-CLI smoke test for the emitted operator system (stdlib unittest).

Static contract-trace proves strings, not execution (advisor HIGH). This test
EXECUTES the emitted /agents/ tree against a MOCK `claude` binary on PATH that
records its argv and emits a dummy response, then asserts the invocation script:
  - passes its pre-flight checks (prompt + foundational docs incl. the now-emitted
    vision.md — foundation-doc wiring makes the script actually runnable);
  - invokes `claude` with the RESOLVED --model + the --context file list + --print;
  - writes the agent output via the atomic temp->final rename;
  - writes a well-formed handoff envelope (status COMPLETE / stop_reason completed).
Plus `bash -n` (syntax check) on every emitted .sh script.

Skipped if bash is unavailable.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from operator_system_emitter import generate_operator_system  # noqa: E402
from emission_plan import load_contract, default_contract_path, validate_emission_plan  # noqa: E402
from test_emission_plan import _valid_plan  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
BASH = shutil.which("bash")

MOCK_CLAUDE = """#!/usr/bin/env bash
# Mock `claude` CLI: record argv (one arg per line) and emit a dummy response.
printf '%s\\n' "$@" >> "$MOCK_CLAUDE_ARGV_LOG"
echo "MOCK_RESPONSE: dummy agent output for smoke test"
exit 0
"""


@unittest.skipIf(BASH is None, "bash not available")
class RuntimeSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(default_contract_path())

    def _emit(self):
        plan = validate_emission_plan(_valid_plan(), self.contract)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        staging = Path(tmp.name) / "system"
        generate_operator_system(plan, staging, REPO_ROOT, generator_version_override="0" * 40)
        return staging

    def _mock_bin(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        mock = d / "claude"
        mock.write_text(MOCK_CLAUDE, encoding="utf-8")
        mock.chmod(0o755)
        return d

    def test_emitted_invocation_script_runs_under_mock_claude(self):
        staging = self._emit()
        mockdir = self._mock_bin()
        argv_log = Path(tempfile.mkdtemp()) / "argv.log"
        self.addCleanup(lambda: shutil.rmtree(argv_log.parent, ignore_errors=True))

        script = staging / "agents" / "scripts" / "researcher.sh"
        self.assertTrue(script.exists(), "researcher invocation script not emitted")

        env = dict(os.environ)
        env["PATH"] = f"{mockdir}{os.pathsep}{env['PATH']}"
        env["MOCK_CLAUDE_ARGV_LOG"] = str(argv_log)
        proc = subprocess.run(
            [BASH, str(script), "smoke001"],
            cwd=str(staging), env=env, capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, f"script failed: {proc.stderr}")

        # The mock claude was invoked with the resolved model + context + print.
        argv = argv_log.read_text(encoding="utf-8")
        self.assertIn("--model", argv)
        self.assertIn("model-standard", argv)  # researcher.primary_model_tier=standard -> resolved
        self.assertIn("--print", argv)
        self.assertIn("agents/prompts/researcher_prompt.md", argv)  # --context prompt
        self.assertIn("vision.md", argv)  # foundational context (now emitted at root)

        # Atomic output written.
        out = staging / "work" / "agent_outputs" / "researcher_smoke001_output.md"
        self.assertTrue(out.exists(), "agent output not written via atomic rename")
        self.assertIn("MOCK_RESPONSE", out.read_text(encoding="utf-8"))

        # Handoff envelope written + well-formed.
        handoff = staging / "agents" / "handoffs" / "researcher_smoke001_handoff.json"
        self.assertTrue(handoff.exists(), "handoff envelope not written")
        env_doc = json.loads(handoff.read_text(encoding="utf-8"))
        self.assertEqual(env_doc["status"], "COMPLETE")
        self.assertEqual(env_doc["stop_reason"], "completed")
        self.assertEqual(env_doc["agent"], "researcher")

    def test_bash_n_on_every_emitted_script(self):
        staging = self._emit()
        scripts = sorted(staging.rglob("*.sh"))
        self.assertTrue(scripts, "no .sh scripts emitted")
        for s in scripts:
            proc = subprocess.run([BASH, "-n", str(s)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"bash -n failed for {s.name}: {proc.stderr}")


if __name__ == "__main__":
    unittest.main()
