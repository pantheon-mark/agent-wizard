"""Content-pin test for Cut 1.3 Task 3 (V15-1 operator payoff).

Task 2 gave the emitted operator project a typed capability-health CLI:
`python3 agents/lib/external_write/capability_health.py --overall`, which prints
JSON including a `normal_status_allowed` boolean. Task 3 wires the EMITTED
session-start sequence to actually consult that command and gate the
session's honest-status claim on its result, so a paused/red capability or an
interrupted run is re-surfaced every session -- durable across a cold reopen --
rather than silently skipped.

This is a content-pin test, not a behavioral one: it asserts the three
emitted template/script sources literally reference the health-check command
and its `normal_status_allowed` key, mirroring the anti-drift constant-pin
style of test_capability_health.TestPathConstantsAntiDrift. If these
assertions ever need to change, the wiring itself changed -- check that was
intentional before updating the pin.
"""

import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_HEALTH_CMD = "agents/lib/external_write/capability_health.py --overall"


class TestSessionStartHealthWiring(unittest.TestCase):
    def _read(self, rel):
        return (_REPO / "wizard" / rel).read_text(encoding="utf-8")

    def test_claude_md_session_start_consults_health(self):
        text = self._read("templates/root/CLAUDE.md")
        self.assertIn(_HEALTH_CMD, text)
        self.assertIn("normal_status_allowed", text)

    def test_orientation_gates_ready_prose_on_health(self):
        text = self._read("skills/orientation.md")
        self.assertIn(_HEALTH_CMD, text)
        self.assertIn("normal_status_allowed", text)

    def test_kickoff_runs_health_check(self):
        text = self._read("scripts/start_session_template.sh")
        self.assertIn("capability_health.py --overall", text)


class TestAcceptanceHandoffIsSingleLine(unittest.TestCase):
    """Task 6 (V15-2): the acceptance hand-off must be one paste-safe line --
    no backslash line-continuations and no path args (--phase-id /
    --copy-run-proof) for the operator to mistype. Pinned in both emitted
    skill docs that carry this command."""

    _FILES = ("skills/next-phase.md", "skills/rebuild-paused-capability.md")

    def _read(self, rel):
        return (_REPO / "wizard" / rel).read_text(encoding="utf-8")

    def test_acceptance_command_is_single_line_in_both_files(self):
        for rel in self._FILES:
            text = self._read(rel)
            with self.subTest(file=rel):
                self.assertIn("operator_acceptance.py --capability-id", text)
                self.assertNotIn("--copy-run-proof \"agents/handoffs", text)
                for line in text.splitlines():
                    if "operator_acceptance.py" in line:
                        self.assertFalse(
                            line.rstrip().endswith("\\"),
                            f"{rel}: acceptance command must be one line: {line!r}",
                        )


if __name__ == "__main__":
    unittest.main()
