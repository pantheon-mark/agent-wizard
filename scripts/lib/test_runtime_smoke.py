"""Runtime smoke + flag-surface guards for the emitted operator system (stdlib unittest).

Two layers, because a mock alone is blind to "can a real operator launch this":

1. Mock-CLI execution — EXECUTES the emitted /agents/ tree against a MOCK `claude`
   binary on PATH that records its argv, then asserts the invocation script:
     - passes its pre-flight checks (prompt + foundational docs incl. vision.md);
     - invokes `claude` with the RESOLVED --model, --append-system-prompt (the prompt
       loaded as system prompt), --permission-mode acceptEdits (headless writes), --print,
       and the foundational docs named for from-disk reading (NOT an invalid --context flag);
     - writes the agent output via the atomic temp->final rename;
     - writes a well-formed handoff envelope (status COMPLETE / stop_reason completed).

2. REAL `claude --help` flag-surface guard (test_emitted_scripts_use_only_real_claude_flags)
   — the mock accepts ANY flag, so it cannot catch an invented flag. This guard validates
   every flag the emitted scripts pass to `claude` against the live `claude --help` surface,
   which is what catches the dogfood runnability class (`--thinking-budget`, `--context`).

Plus `bash -n` (syntax check) on every emitted .sh script. Skipped if bash is unavailable.
"""

import json
import os
import re
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
from test_agent_record_assembler import mandated_writes, write_target_covered  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
BASH = shutil.which("bash")
CLAUDE = shutil.which("claude")


def _real_claude_flag_surface():
    """The REAL flag set the installed `claude` CLI accepts, parsed live from `claude --help`.

    This is the external source of truth for the flag guard: every flag an emitted script
    passes to `claude` must be in this set, so an invented flag (`--thinking-budget`,
    `--context`) fails the build and the surface self-updates as the CLI evolves. Parsing the
    help text (rather than a pinned allowlist) is what keeps the guard from drifting out of
    conformance silently."""
    out = subprocess.run([CLAUDE, "--help"], capture_output=True, text=True).stdout
    long_flags = set(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", out))
    short_flags = set(re.findall(r"(?<![\w-])(-[A-Za-z])(?=[ ,])", out))
    return long_flags | short_flags


def _claude_invocation_flags(script_text):
    """Extract every flag PASSED TO `claude` in a bash script — NOT the script's own
    arg-parsing flags (e.g. start-session.sh's `--resume`/`--alert`, which live in a `case`
    block, never in the claude invocation). Follows backslash line-continuations; collects
    every '-'-prefixed token of the invocation; resolves bash array expansions
    (`"${CONTEXT_ARGS[@]}"`) back to the `ARR+=("--flag" ...)` literals that built them (so an
    array-assembled bad flag like the original `--context` is caught, not just direct flags);
    and STOPS at the quoted positional prompt so flag-looking text inside the prompt is not
    scanned."""
    flags = set()
    array_refs = set()
    lines = script_text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip().startswith("#") and re.search(r"(^|\s|\|)claude(\s|\\|$)", raw):
            block = [raw]
            cur = raw
            while cur.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                cur = lines[i]
                block.append(cur)
            # strip everything up to and including the `claude` word on the first line
            first = re.sub(r"^.*?\bclaude\b", "", block[0])
            for seg in [first] + block[1:]:
                s = seg.strip().rstrip("\\").strip()
                # a quoted segment with no array marker is the positional prompt -> stop
                if (s.startswith('"') or s.startswith("'")) and "[@]" not in s:
                    break
                for m in re.finditer(r"\$\{(\w+)\[@\]", seg):
                    array_refs.add(m.group(1))  # flags assembled into this array reach claude
                for tok in s.split():
                    if tok.startswith("-"):
                        flags.add(tok)
        i += 1
    # resolve array-built flags: ARR+=("--flag" ...) / ARR=("--flag" ...)
    for name in array_refs:
        for m in re.finditer(rf"{name}\+?=\((.*?)\)", script_text, re.S):
            for dq, sq in re.findall(r'"(-{1,2}[^"]*)"|\'(-{1,2}[^\']*)\'', m.group(1)):
                lit = (dq or sq).split()
                if lit:
                    flags.add(lit[0])
    return flags


def _autonomy_levels_in(text):
    """Every autonomy-level digit stated in level contexts in a doc (handles the four
    phrasings: 'Autonomy level | N', 'Current level: **N**', 'Current autonomy level: N',
    '(Level N)'). Returned as a set so an internally- or cross-doc-inconsistent level is
    visible as a set with >1 member."""
    return set(re.findall(
        r"(?:autonomy\s+level|current\s+(?:autonomy\s+)?level|\(level)\D{0,10}?(\d)", text, re.I))


def _autonomous_actions_body(project_instructions_text):
    """The body of the 'What the system may do without asking' section (between that heading
    and the next '### ' heading)."""
    m = re.search(r"may do without asking[^\n]*\n(.*?)\n###",
                  project_instructions_text, re.S | re.I)
    return m.group(1) if m else ""


def _permitted_writes_in_prompt(prompt_text):
    """The permitted-write entries rendered under a prompt's permission-boundary section
    ('Write to the following directories and files only:'). Strips bullet markup, backticks,
    and any trailing ' — description'."""
    out = []
    grabbing = False
    for ln in prompt_text.splitlines():
        if "Write to the following directories and files only" in ln:
            grabbing = True
            continue
        if grabbing:
            s = ln.strip()
            if s.startswith(("-", "*")):
                item = s.lstrip("-* ").strip()
                item = re.split(r"\s+[—-]\s+", item)[0].strip().strip("`")
                if item:
                    out.append(item)
            elif s == "":
                continue
            else:
                break
    return out

MOCK_CLAUDE = """#!/usr/bin/env bash
# Mock `claude` CLI: record argv (one arg per line) and emit a dummy response.
# Simulates the agent's stop-reason self-report: when $MOCK_STOP_REASON is set, it
# extracts the sentinel path the invocation script named in the task prompt
# ("Stop-reason sentinel: <path>") and writes the stop reason there, exactly as a
# real agent would. Exit code is $MOCK_EXIT_CODE (default 0) so a test can drive the
# process-failure branch.
printf '%s\\n' "$@" >> "$MOCK_CLAUDE_ARGV_LOG"
if [[ -n "${MOCK_STOP_REASON:-}" ]]; then
  sentinel="$(printf '%s\\n' "$@" | sed -n 's/.*Stop-reason sentinel: //p' | head -1)"
  [[ -n "$sentinel" ]] && printf '%s' "$MOCK_STOP_REASON" > "$sentinel"
fi
echo "MOCK_RESPONSE: dummy agent output for smoke test"
exit "${MOCK_EXIT_CODE:-0}"
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
        # New invocation contract: the prompt is loaded via --append-system-prompt
        # (its CONTENT, not a path), the headless agent runs under --permission-mode acceptEdits,
        # the foundational docs are named for from-disk reading, and the invalid --context flag
        # is gone.
        self.assertIn("--append-system-prompt", argv)
        self.assertIn("--permission-mode", argv)
        self.assertIn("acceptEdits", argv)
        self.assertNotIn("--context", argv)
        self.assertIn("Permission boundary", argv)  # the appended system prompt = the prompt file content
        self.assertIn("vision.md", argv)  # named in the task prompt as a from-disk read

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

    def _run_emitted_script(self, staging, agent="researcher", task_id="smoke001", extra_env=None):
        """Run an emitted invocation script under the mock claude; return (proc, handoff_doc_or_None)."""
        mockdir = self._mock_bin()
        argv_log = Path(tempfile.mkdtemp()) / "argv.log"
        self.addCleanup(lambda: shutil.rmtree(argv_log.parent, ignore_errors=True))
        env = dict(os.environ)
        env["PATH"] = f"{mockdir}{os.pathsep}{env['PATH']}"
        env["MOCK_CLAUDE_ARGV_LOG"] = str(argv_log)
        if extra_env:
            env.update(extra_env)
        script = staging / "agents" / "scripts" / f"{agent}.sh"
        proc = subprocess.run([BASH, str(script), task_id], cwd=str(staging),
                              env=env, capture_output=True, text=True)
        handoff = staging / "agents" / "handoffs" / f"{agent}_{task_id}_handoff.json"
        doc = json.loads(handoff.read_text(encoding="utf-8")) if handoff.exists() else None
        return proc, doc

    def test_invocation_script_publishes_agent_reported_stop_reason(self):
        """SINGLE-OWNER + FIDELITY: on a clean exit, the script publishes the stop reason the
        agent self-reported via the sentinel (here 'deferred') — NOT a hardcoded 'completed'.
        This is the core false-positive-completion fix: an agent that defers/exceeds-budget and
        exits 0 must NOT be stamped 'completed', or the Orchestrator's defer/budget logic never
        fires."""
        staging = self._emit()
        proc, doc = self._run_emitted_script(staging, extra_env={"MOCK_STOP_REASON": "deferred"})
        self.assertEqual(proc.returncode, 0, f"script failed: {proc.stderr}")
        self.assertIsNotNone(doc, "handoff envelope not written")
        self.assertEqual(doc["stop_reason"], "deferred",
                         "agent-reported stop reason must survive into the envelope")
        self.assertEqual(doc["agent"], "researcher")

    def test_invocation_script_defaults_stop_reason_when_agent_silent(self):
        """When the agent writes no (or an invalid) stop-reason sentinel on a clean exit, the
        script writes a deterministic 'completed' envelope AND flags that it defaulted, so a
        silent agent is distinguishable from a genuine 'completed' self-report."""
        staging = self._emit()
        proc, doc = self._run_emitted_script(staging)  # no MOCK_STOP_REASON -> agent silent
        self.assertEqual(proc.returncode, 0, f"script failed: {proc.stderr}")
        self.assertEqual(doc["stop_reason"], "completed")
        self.assertTrue(any("default" in str(f).lower() or "fallback" in str(f).lower()
                            for f in doc.get("flags", [])),
                        f"expected a script-default marker flag, got flags={doc.get('flags')}")

    def test_invocation_script_failure_is_authoritative_over_sentinel(self):
        """PROCESS FAILURE IS GROUND TRUTH: even if the agent reported 'completed', a nonzero
        exit must publish status FAILED / stop_reason error — the sentinel cannot mask a crash."""
        staging = self._emit()
        proc, doc = self._run_emitted_script(
            staging, extra_env={"MOCK_STOP_REASON": "completed", "MOCK_EXIT_CODE": "3"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(doc["status"], "FAILED")
        self.assertEqual(doc["stop_reason"], "error")

    def test_high_tier_launch_has_graceful_1m_fallback(self):
        """F-05: the high tier resolves to the 1M-context variant (model-id [1m] suffix), which
        is not available on every account/plan. The emitted launch scripts must therefore name
        a graceful --fallback-model so a 1M-less account degrades to the standard context window
        instead of failing at launch. Covers start-session.sh (the operator's main session) and
        every emitted agent invocation script. (--fallback-model is a real claude flag, so the
        flag-surface guard stays green.)"""
        staging = self._emit()
        targets = [staging / "start-session.sh"] + sorted((staging / "agents" / "scripts").glob("*.sh"))
        missing = [t.name for t in targets
                   if "--fallback-model" not in t.read_text(encoding="utf-8")]
        self.assertEqual(missing, [],
                         "F-05: emitted launch scripts must name a graceful --fallback-model for "
                         f"the [1m] high tier (degrade to standard context if 1M unavailable); "
                         f"missing in: {missing}")

    def test_bash_n_on_every_emitted_script(self):
        staging = self._emit()
        scripts = sorted(staging.rglob("*.sh"))
        self.assertTrue(scripts, "no .sh scripts emitted")
        for s in scripts:
            proc = subprocess.run([BASH, "-n", str(s)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, f"bash -n failed for {s.name}: {proc.stderr}")

    def test_emitted_scripts_use_only_real_claude_flags(self):
        """RUNNABILITY GUARD (anti-overfit: input-independent invariant on EVERY emitted *.sh).

        Validates the emitted invocations against the REAL `claude --help` surface instead of
        a mock that accepts any flag. Catches the dogfood bug class — `--thinking-budget`
        (start-session.sh) and `--context` (agent scripts) are not real flags, so the emitted
        system was un-launchable while the old mock-based smoke test passed."""
        if CLAUDE is None:
            self.skipTest("claude CLI not on PATH")
        staging = self._emit()
        real = _real_claude_flag_surface()
        offenders = {}
        for script in sorted(staging.rglob("*.sh")):
            bad = sorted(_claude_invocation_flags(script.read_text(encoding="utf-8")) - real)
            if bad:
                offenders[script.name] = bad
        self.assertEqual(
            offenders, {},
            f"emitted scripts pass flags the real `claude` CLI does not accept: {offenders}")

    def test_each_emitted_agent_prompt_permits_its_mandated_writes(self):
        """PERMISSION-BOUNDARY GUARD on the EMITTED artifact: for every emitted agent prompt
        that declares a permission boundary, the writes it mandates (parsed from its own body)
        must all sit within its permitted-write set. Complements the assembler-level guard by
        also covering the agent_emitter rendering path."""
        staging = self._emit()
        prompts = sorted((staging / "agents" / "prompts").glob("*.md"))
        self.assertTrue(prompts, "no agent prompts emitted")
        checked = 0
        offenders = {}
        for p in prompts:
            text = p.read_text(encoding="utf-8")
            if "Write to the following directories and files only" not in text:
                continue  # a prompt with a differently-shaped boundary (e.g. orchestrator)
            checked += 1
            permitted = _permitted_writes_in_prompt(text)
            uncovered = sorted(m for m in mandated_writes(text)
                               if not write_target_covered(m, permitted))
            if uncovered:
                offenders[p.name] = {"uncovered": uncovered, "permitted": permitted}
        self.assertTrue(checked, "no agent prompt with a standard permission boundary was checked")
        self.assertEqual(offenders, {},
                         f"emitted agent prompts mandate writes outside their permitted set: {offenders}")

    def test_autonomy_level_consistent_across_docs_and_body_wired(self):
        """AUTONOMY GUARD (anti-overfit: emits at levels 1/2/3 so a HARDCODED level fails).

        Asserts, at whatever level is derived: (a) CLAUDE.md / project_instructions.md /
        execution_plan.md / session_bootstrap.md all state the SAME autonomy level; (b) the
        'may do without asking' body is non-empty (wired, not the inert empty default);
        (c) no inert '(Level N default)' literal remains. The estate dogfood bug — a hardcoded
        'Level 2' in project_instructions vs the derived Level 1 elsewhere — is invisible at
        the fixture's default level 2, so testing 1 and 3 is what catches it."""
        for level in ("1", "2", "3"):
            plan_dict = _valid_plan()
            plan_dict["foundation_doc_inputs"]["AUTONOMY_LEVEL"] = level
            plan = validate_emission_plan(plan_dict, self.contract)
            tmp = tempfile.TemporaryDirectory()
            self.addCleanup(tmp.cleanup)
            staging = Path(tmp.name) / "system"
            generate_operator_system(plan, staging, REPO_ROOT, generator_version_override="0" * 40)

            docs = {n: (staging / n).read_text(encoding="utf-8") for n in (
                "CLAUDE.md", "project_instructions.md", "execution_plan.md", "session_bootstrap.md")}
            for name, text in docs.items():
                self.assertEqual(
                    _autonomy_levels_in(text), {level},
                    f"derived level {level}: {name} states autonomy level(s) "
                    f"{sorted(_autonomy_levels_in(text))} (expected just {level})")

            pi = docs["project_instructions.md"]
            self.assertNotRegex(pi, r"\(Level \d default\)",
                                f"level {level}: inert hardcoded-level literal remains in project_instructions.md")
            self.assertTrue(_autonomous_actions_body(pi).strip(),
                            f"level {level}: the 'may do without asking' body is empty (unwired)")


class HandoffContractTests(unittest.TestCase):
    """Static contract guards on the handoff-envelope ownership model (no bash needed).

    The envelope has ONE owner: the invocation script writes it (deterministically, from the
    agent's reported stop reason + the process exit status). The agent reports its stop reason
    via a sentinel, and does NOT itself write a competing JSON envelope at the canonical path.
    The Orchestrator's documented read path must match the writer's path (agent-prefixed)."""

    def test_orchestrator_documents_agent_prefixed_handoff_path(self):
        """The Orchestrator's documented handoff read path must carry the agent-name prefix —
        the writer emits {agent}_{task_id}_handoff.json, so a bare [task_id]_handoff.json path
        sends the Orchestrator looking where no file exists."""
        text = (REPO_ROOT / "wizard" / "agents" / "orchestrator_prompt.md").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"handoffs/\[task_id\]_handoff\.json",
                            "orchestrator documents the bare [task_id] path (missing agent prefix)")
        self.assertRegex(text, r"\[agent[_a-z]*\]_\[task_id\]_handoff\.json",
                         "orchestrator should document the agent-prefixed handoff path")

    def test_agent_prompt_reports_stop_reason_not_full_envelope(self):
        """The specialist prompt must instruct the agent to report its stop reason (sentinel),
        and must NOT instruct it to write a full JSON handoff envelope at the canonical
        {AGENT_NAME}_[task_id]_handoff.json path — that path has a single owner (the script)."""
        text = (REPO_ROOT / "wizard" / "agents" / "agent_prompt_template.md").read_text(encoding="utf-8")
        self.assertIn("stop reason", text.lower(),
                      "agent prompt should instruct the agent to report its stop reason")
        self.assertNotRegex(
            text, r"write a handoff envelope to[^\n]*\{\{AGENT_NAME\}\}_\[task_id\]_handoff\.json",
            "agent prompt must not write the canonical handoff envelope (single-owner = the script)")


if __name__ == "__main__":
    unittest.main()
