"""ANTI-DRIFT (Cut 1.6 / Task 7): every tool path an emitted skill tells the
operator to run must exist where the skill says it does.

F-VAL19-2: `rebuild-paused-capability.md` instructed
``python3 agents/lib/external_write/capability_code_scaffold.py ...``. That file
is NOT in the operator project and never is -- ``capability_code_scaffold.py`` is
TOOLKIT engine code, shipped by ``wizard self-update`` and living in the wizard's
own home. The skill named an emitted-lib path for a toolkit tool, **on the
critical repair path for every paused capability**. A capable agent recovered by
searching the wizard home; a naive one dead-ends exactly where the operator most
needs it to work.

The fix is not just correcting the string -- it is binding the claim to reality,
so the next reorganisation cannot silently reintroduce it. Same discipline as
``feedback_derive_enforcement_scope_from_emitter_output``: derive the check from
where the producer actually puts things, never from a hand-maintained list.

Run:  python3 -m unittest discover -s wizard/scripts/lib \\
          -p test_skill_path_antidrift.py
"""

import re
import unittest
from pathlib import Path

_WIZARD = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _WIZARD / "skills"

#: Where each shipping surface actually lives, derived from the real tree.
_EMITTED_LIB_DIR = _WIZARD / "agents" / "lib" / "external_write"
_TOOLKIT_LIB_DIR = _WIZARD / "scripts" / "lib"

#: `python3 <path>.py` invocations in skill markdown.
_INVOCATION = re.compile(r"python3\s+[\"']?([A-Za-z0-9_./${}:\-]+\.py)")


class SkillToolPathAntiDriftTests(unittest.TestCase):

    def _cited_paths(self):
        """(skill_file, cited_path) for every python3 invocation in every
        emitted skill."""
        for skill in sorted(_SKILLS_DIR.glob("*.md")):
            text = skill.read_text(encoding="utf-8")
            for match in _INVOCATION.finditer(text):
                yield skill, match.group(1)

    def test_every_cited_tool_exists_where_the_skill_says_it_does(self):
        """The core binding. An operator-project-relative path must resolve in
        the EMITTED lib; a toolkit tool must be cited via the wizard home, never
        as though it were in the project."""
        problems = []
        for skill, cited in self._cited_paths():
            basename = Path(cited).name

            if cited.startswith("${WIZARD_HOME") or "agent-wizard" in cited:
                # Cited as a toolkit tool -- it must really be one.
                if not (_TOOLKIT_LIB_DIR / basename).is_file():
                    problems.append(
                        f"{skill.name}: cites `{cited}` as a wizard-home toolkit tool, "
                        f"but {basename} is not in wizard/scripts/lib/")
                continue

            if cited.startswith("agents/lib/external_write/"):
                if (_EMITTED_LIB_DIR / basename).is_file():
                    continue
                where = ("wizard/scripts/lib/ (a TOOLKIT tool -- cite it via "
                         "${WIZARD_HOME:-$HOME/agent-wizard}/scripts/lib/)"
                         if (_TOOLKIT_LIB_DIR / basename).is_file()
                         else "nowhere in this repo")
                problems.append(
                    f"{skill.name}: tells the operator to run `{cited}`, but "
                    f"{basename} is not in the emitted lib -- it is in {where}")

        self.assertEqual(problems, [], "skill tool-path drift:\n  " + "\n  ".join(problems))

    def test_the_f_val19_2_case_specifically(self):
        """A named regression for the exact defect, so it cannot come back
        quietly under a reorganisation that happens to keep the generic test
        green."""
        self.assertFalse(
            (_EMITTED_LIB_DIR / "capability_code_scaffold.py").exists(),
            "capability_code_scaffold.py is toolkit engine code -- if it ever "
            "appears in the emitted lib, this test's premise changed and the "
            "skill guidance must be revisited deliberately")
        self.assertTrue((_TOOLKIT_LIB_DIR / "capability_code_scaffold.py").is_file())

        rebuild = (_SKILLS_DIR / "rebuild-paused-capability.md").read_text(encoding="utf-8")
        self.assertNotIn(
            "agents/lib/external_write/capability_code_scaffold.py", rebuild,
            "the rebuild skill must not send the operator to a path that does not "
            "exist in their project -- this is on the critical repair path for "
            "EVERY paused capability (F-VAL19-2)")

    def test_health_checks_in_the_rebuild_skill_use_overall(self):
        """F-PRE-6: the bare per-capability form is exactly the view F-VAL18-1
        proved blind to relpath-keyed bespoke-writer entries."""
        rebuild = (_SKILLS_DIR / "rebuild-paused-capability.md").read_text(encoding="utf-8")
        bare = re.findall(r"capability_health\.py\s+\.(?!\s*--overall)", rebuild)
        self.assertEqual(
            bare, [],
            "every capability_health invocation in the rebuild skill must pass "
            "--overall; the bare per-capability view cannot see bespoke-writer entries")


if __name__ == "__main__":
    unittest.main()
