"""PERMANENT GATE (Cut 1.6 / Task 6): a freshly scaffolded capability that must
READ external data is BOTH scan-clean AND runnable.

This is the STEP 0 fixture, promoted. It is the check that would have caught
F-VAL19-5 three cuts earlier.

WHY BOTH PROPERTIES IN ONE TEST -- do not split them. Checking either alone is
exactly what let this ship three times:

  * The v0.15.0/v0.16.0 fresh-build e2e proved a fresh capability was SCAN-CLEAN
    and concluded fresh builds were fine.
  * Nothing proved it was RUNNABLE. It was not: the scaffold emitted three files
    with no entrypoint, deferring the credential seam to "whoever wires this
    capability's entrypoint together" -- and every place to do that in an
    operator project is CAPABILITY-zoned, where obtaining a read client is a
    scan violation.

A writer that complied could not read; a writer that read could not comply. The
gap was invisible to a scan-only gate because the compliant shape scans
perfectly -- it just cannot work. See
``external_review/v0.19.0_step0_fresh_build_read_gap_2026-07-25.md``.

Run:  python3 -m unittest discover -s wizard/scripts/lib \\
          -p test_fresh_emit_read_capability.py
"""

import ast
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_WIZARD = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _WIZARD / "scripts" / "lib"
_AGENTS_LIB = _WIZARD / "agents" / "lib"
for _p in (str(_SCRIPTS_LIB), str(_AGENTS_LIB)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from capability_code_scaffold import (  # noqa: E402
    CapabilityCodeSpec, emit_capability_code_scaffold,
)


def _read_dependent_spec():
    """A capability whose op REQUIRES a capability-side read to build its
    proposal -- i.e. every bulk whittle. A write-only capability would not have
    exercised the gap."""
    return CapabilityCodeSpec(
        capability_id="vendor_cleanup",
        display_name="Vendor Record Cleanup",
        op_kind="archive_vendor_record",
        surface="acme_crm",
        read_only_scope="acme.records.readonly",
        blast_radius_cap=50,
        read_methods=("list_records", "get_record"),
    )


class FreshEmitReadCapabilityGate(unittest.TestCase):

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        # A real operator project: the emitted lib, then a real emit through the
        # real producer entrypoint (never a hand-built stand-in).
        lib_dst = self.root / "agents" / "lib" / "external_write"
        lib_dst.parent.mkdir(parents=True)
        shutil.copytree(_AGENTS_LIB / "external_write", lib_dst,
                        ignore=shutil.ignore_patterns("__pycache__", "test_*.py"))
        (self.root / "agents" / "capabilities").mkdir(parents=True, exist_ok=True)
        emit_capability_code_scaffold(_read_dependent_spec(), self.root)

    def _capability_src(self):
        return (self.root / "agents" / "capabilities"
                / "vendor_cleanup_capability.py").read_text(encoding="utf-8")

    # ------------------------------------------------------ property 1: CLEAN

    def test_a_fresh_read_dependent_capability_is_scan_clean(self):
        """The property the old e2e checked -- necessary, and on its own
        insufficient."""
        result = subprocess.run(
            [sys.executable, "agents/lib/external_write/scan.py", "agents/"],
            cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0,
                         f"fresh emit must be scan-clean:\n{result.stdout}{result.stderr}")

    # --------------------------------------------------- property 2: RUNNABLE

    def test_a_fresh_read_dependent_capability_can_actually_read(self):
        """The property nothing checked before Cut 1.6, and the whole point.

        Runs in a subprocess against the EMITTED tree so the emitted lib is what
        executes -- not the build-side copy already imported into this process.
        The adapter's provisioner is stubbed (a real one needs live vendor
        credentials); everything else is the real emitted wiring."""
        # Fill in ONLY the single documented TODO the scaffold emits for
        # vendor-specific auth -- the one thing the emitter genuinely cannot
        # write. If a fresh capability needs MORE than that to read, the
        # scaffold is incomplete, which is exactly the F-VAL19-5 condition.
        #
        # (The provisioner cannot be monkey-patched after import: the registry
        # CAPTURES the class-bound method at register_adapter time precisely so
        # instance/class patching is inert -- ADR-0039's captured-dispatch
        # property. So the TODO is filled in the source, before import, which is
        # also what a real operator build does.)
        adapter_path = (self.root / "agents" / "lib" / "external_write"
                        / "adapters_vendor_cleanup.py")
        src = adapter_path.read_text(encoding="utf-8")
        todo_start = src.index("    def build_read_only_client(self, op: Any) -> Any:")
        todo_end = src.index("\n\n", src.index("here and return it.", todo_start))
        filled = (src[:todo_start]
                  + "    def build_read_only_client(self, op: Any) -> Any:\n"
                    "        class _C:\n"
                    "            def list_records(self):\n"
                    "                return ['r1', 'r2']\n"
                    "        return _C()"
                  + src[todo_end:])
        adapter_path.write_text(filled, encoding="utf-8")

        harness = self.root / "_gate_probe.py"
        harness.write_text(
            "import sys\n"
            "sys.path.insert(0, 'agents/lib')\n"
            "from external_write import adapters_vendor_cleanup  # registers\n"
            "from external_write import capability_runner as CR\n"
            "facade = CR.build_capability_read_facade('.', 'vendor_cleanup')\n"
            "print('READ_OK', list(facade.list_records()))\n",
            encoding="utf-8")

        result = subprocess.run([sys.executable, "_gate_probe.py"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertIn("READ_OK", result.stdout,
                      "a freshly scaffolded read-dependent capability must be able to "
                      "obtain a WORKING read facade after only its documented vendor-auth "
                      f"TODO is filled in:\n{result.stdout}{result.stderr}")
        self.assertIn("r1", result.stdout)

    # --------------------------------------------- the shape that caused it

    def test_the_capability_has_nothing_to_wire(self):
        """The emitted capability names no client, no adapter, no facade class,
        and carries no hand-off note -- because the kernel injects. That
        deferral WAS the root cause, not a documentation wart."""
        src = self._capability_src()
        # AST, not grep: the docstring legitimately NAMES the adapter and facade
        # class in order to say it never imports them. Grepping raw text would
        # flag that prose -- the same text-vs-structure mistake this cut fixed
        # in the state classifier's reference detection.
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        self.assertFalse([m for m in imported if "adapters_" in m],
                         f"must not import any adapter module: {sorted(imported)}")
        self.assertNotIn("external_write.capability_api.build_read_facade", imported)
        self.assertNotIn("external_write.read_facade", imported)

        # No client-building or hand-off remains in the emitted CODE.
        defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertNotIn("build_facade", defined)
        self.assertIn("propose_operations", defined)
        # Positive assertion instead of grepping for an absent phrase: the
        # module must TELL you it is called by the kernel. (The docstring does
        # also recount the old hand-off as history, which is why an
        # absence-of-phrase check would be self-tripping.)
        self.assertIn("capability_runner.py", src,
                      "the emitted module must name how it is actually run")

    def test_the_emitted_adapter_exposes_the_provisioner_on_the_class(self):
        """F-STEP0-1's regression guard, asserted on a REAL emit: a name-grep
        found this symbol everywhere and looked wired, while the registry's
        getattr(cls, ...) found nothing."""
        adapter_src = (self.root / "agents" / "lib" / "external_write"
                       / "adapters_vendor_cleanup.py").read_text(encoding="utf-8")
        tree = ast.parse(adapter_src)
        cls = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and n.name == "VendorCleanupAdapter")
        self.assertIn("build_read_only_client",
                      {b.name for b in cls.body if isinstance(b, ast.FunctionDef)})
        self.assertNotIn("\ndef build_read_only_client(", adapter_src)


if __name__ == "__main__":
    unittest.main()
