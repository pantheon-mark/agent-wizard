"""BYTE-PARITY guard for the bundle-sourced operating-layer emit refactor.

Task A2 changes WHERE emit reads its wizard-authored operating-layer templates
from: instead of the live `wizard/templates/`, `wizard/agents/`, `wizard/scripts/`
trees, emit sources every `delivery: "wizard"` template from the versioned system
bundle's `templates/` tree (the single frozen template home, per the contract's
`template_path`). Foundation-doc templates were already bundle-sourced.

This test PROVES the relocation changed NOTHING: a fresh full emit on the preserved
pilot transcript must reproduce, byte-for-byte (canonical LF-normalized sha256),
every `delivery: "wizard"` file's recorded baseline hash. The baseline
(`emit_parity_baseline.json`) was captured on `main` BEFORE the refactor.

Scope:
  - Only `delivery: "wizard"` files are parity-checked. `operator_derived` files
    (prd.md, agents/roster.md, the four acceptance contracts) keep their existing
    Python emit path and are NOT a delivery target — out of scope here.
  - The baseline is hashes only (not the whole emitted tree), per the task's
    "commit the hash fixture, not the tree" instruction.

If any `delivery: "wizard"` file's bytes change, the refactor introduced drift and
this test fails naming the file. The fixture is regenerated ONLY for a deliberate,
reviewed output change — never to make a red parity test pass.

Skips when the preserved pilot transcript / registered bundle are unavailable
(same prereq guard as the other real-transcript e2e tests).

Stdlib unittest; pip-install-free.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))            # wizard/scripts/lib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))        # wizard/scripts (interview_cli)

from upgrade import sha256_file  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
BUNDLE_VERSION = "v0.5.0"
CONTRACT_PATH = REPO_ROOT / "wizard" / "foundation-bundles" / BUNDLE_VERSION / "system-artifacts.json"
BASELINE_PATH = Path(__file__).resolve().parent / "emit_parity_baseline.json"
TRANSCRIPT = Path.home() / "wizard-pilot-2026-06-01" / "wizard_transcript.jsonl"
REGISTRY_PATH = REPO_ROOT / "wizard" / "registry" / "foundation-bundles.json"


def _baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _have_prereqs() -> bool:
    if not TRANSCRIPT.exists() or not REGISTRY_PATH.exists():
        return False
    if not BASELINE_PATH.exists() or not CONTRACT_PATH.exists():
        return False
    try:
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    b = _baseline()
    versions = {e.get("foundation_bundle_version") for e in reg.get("bundles", [])}
    return b["emit_bundle_version"] in versions and BUNDLE_VERSION in versions


@unittest.skipUnless(
    _have_prereqs(),
    f"requires the preserved pilot transcript at {TRANSCRIPT}, the parity baseline, "
    f"and the registered bundles",
)
class EmitParityBundleSourced(unittest.TestCase):
    """A fresh full emit is byte-identical to the pre-refactor baseline for every
    delivery:wizard file (the relocation is a pure source move, zero output change)."""

    def _emit(self, name: str) -> Path:
        import interview_cli as cli  # noqa: E402
        b = _baseline()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        proj = Path(td.name) / name
        cli.cmd_emit_system(
            str(TRANSCRIPT), b["shape"], str(proj), str(REPO_ROOT),
            bundle_version=b["emit_bundle_version"],
            generator_version_override=b["generator_version_override"],
        )
        return proj

    def test_delivery_wizard_files_are_byte_identical_to_baseline(self):
        b = _baseline()
        expected = b["hashes"]
        proj = self._emit("parity-estate")

        # Every baselined delivery:wizard file must exist and hash-match.
        mismatches = []
        missing = []
        for rel, exp_hash in sorted(expected.items()):
            f = proj / rel
            if not f.is_file():
                missing.append(rel)
                continue
            got = "sha256:" + sha256_file(f)
            if got != exp_hash:
                mismatches.append(rel)
        self.assertEqual(missing, [], f"delivery:wizard files MISSING from fresh emit: {missing}")
        self.assertEqual(
            mismatches, [],
            f"BYTE-PARITY BREAK: delivery:wizard file(s) changed bytes vs the pre-refactor "
            f"baseline: {mismatches}. The bundle-sourcing refactor must change NO output.",
        )

    def test_baseline_covers_exactly_the_delivery_wizard_contract_set(self):
        """The baseline's keys == the contract's delivery:wizard set (closed). Guards
        against a file silently dropping out of the parity surface — a delivery:wizard
        file added/removed without updating the baseline would be invisible drift."""
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        contract_wizard = {a["relpath"] for a in contract["artifacts"]
                           if a.get("delivery") == "wizard"}
        baselined = set(_baseline()["hashes"])
        self.assertEqual(
            baselined, contract_wizard,
            "parity baseline keys diverge from the contract's delivery:wizard set "
            f"(only-in-baseline={sorted(baselined - contract_wizard)}, "
            f"only-in-contract={sorted(contract_wizard - baselined)})",
        )


if __name__ == "__main__":
    unittest.main()
