"""Hermetic lifecycle-state test fixture (Task A3, F-71).

Why this exists
----------------
F-71 (verified in the field): a capability-added test class asserted that the write gate
REFUSES a write while its op_kind is "paused pending migration" -- a real, legitimate thing
to want proof of -- but it called ``write_gate.evaluate_write_gate(...)`` with no
``paused_root`` argument, so the gate fell back to its own ambient default
(``write_gate.PAUSED_MECHANISMS_DIR``, the REAL project's ``.wizard/paused-mechanisms/``
directory, resolved relative to whatever the current working directory happens to be when the
test runs). The test's pass/fail outcome therefore depended on the project's OWN transient,
lifecycle-phase-dependent state rather than on anything the test itself set up: it was green
while a stale pause marker happened to still be on disk, then went RED -- on an otherwise
correctly-rebuilt capability -- the moment that marker was cleared (by re-acceptance +
``lifecycle_state.reconcile_state``, Tasks A1/A2). Re-running the exact same test file gives a
DIFFERENT verdict depending on when, in the capability's own pause/rebuild/re-accept
lifecycle, it happens to run -- a non-idempotent self-QA signal, not a real regression.

The root design fix (see ``next-phase.md``'s rebuild-guidance section) is that pause-refusal
enforcement is the DISPATCHER's concern -- ``write_gate.evaluate_write_gate`` and its own test
suite already prove it, once, for every capability -- so a capability's OWN test should not
re-prove it against ambient state at all. If a capability's own test genuinely needs to
exercise lifecycle-dependent behavior (rare -- most capabilities never need to), it must do so
HERMETICALLY: build its own throwaway pause-marker directory and pass it in explicitly, never
read or write the real project's own ``.wizard/paused-mechanisms/``.

What this module provides
--------------------------
``hermetic_paused_mechanisms`` -- a context manager that creates a FRESH ``tempfile.mkdtemp()``
directory (never the real project root, never anything under it), optionally pre-populates it
with one pause marker naming exactly the op_kinds the caller wants treated as paused, yields
that temp directory's path (a plain ``str``, ready to pass straight through as
``evaluate_write_gate(..., paused_root=<that path>)``), and removes the directory again on
exit -- regardless of whether the ``with`` block raised. A capability test that needs to prove
paused-refusal behavior imports this and writes:

    from external_write.lifecycle_test_fixtures import hermetic_paused_mechanisms

    class TestPausedRefusalHermetic(unittest.TestCase):
        def test_refused_while_paused(self):
            with hermetic_paused_mechanisms(["my_op_kind"]) as paused_root:
                d = evaluate_write_gate(op, target="live", paused_root=paused_root, ...)
            self.assertFalse(d.permitted)

or, inside ``setUp`` (this project targets Python 3.11+, so ``TestCase.enterContext`` is
available and registers its own cleanup automatically -- no separate ``tearDown`` needed):

    def setUp(self):
        self.paused_root = self.enterContext(hermetic_paused_mechanisms(["my_op_kind"]))

Either shape gives an IDENTICAL verdict every time, regardless of the real project's own
ambient pause state at the moment the test happens to run -- exactly the property the F-71
test lacked. Passing no op_kinds at all (``hermetic_paused_mechanisms()``) yields a directory
that EXISTS but contains no marker files, which resolves through
``write_gate._load_paused_op_kinds`` to the empty set -- the hermetic equivalent of "nothing is
paused," for a test that wants to prove the UNPAUSED path instead.

What this module deliberately does NOT do
------------------------------------------
It never reads, writes, or otherwise touches the real project's own
``write_gate.PAUSED_MECHANISMS_DIR`` (``.wizard/paused-mechanisms/``) -- that is precisely the
ambient state a hermetic test must never depend on. It carries no dependency on
``write_gate`` at all (a plain marker-directory builder, decoupled from the module that reads
it), so it stays usable for a future lifecycle-dependent check that reads pause state some
other way, not only through ``evaluate_write_gate``.

Stdlib only -- this module ships into the operator's own runtime, ``agents/lib/external_write/``,
alongside every other module in this package.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

__all__ = ["hermetic_paused_mechanisms"]


@contextmanager
def hermetic_paused_mechanisms(
    paused_op_kinds: Sequence[str] = (),
    *,
    marker_name: str = "fixture",
) -> Iterator[str]:
    """Yield a fresh, isolated temp directory shaped like a ``paused-mechanisms`` marker
    directory -- never the real project's own -- suitable to pass straight through as
    ``evaluate_write_gate(..., paused_root=<yielded path>)``.

    paused_op_kinds: the op_kind(s) this hermetic marker should name as paused. If empty
        (the default), the directory is created but left EMPTY -- the hermetic "nothing is
        paused" state (``write_gate._load_paused_op_kinds`` reads an existing-but-empty
        directory as the empty set, never as "absent" or "unreadable" -- see that function's
        own docstring). If non-empty, exactly one marker file named
        ``"{marker_name}.json"`` is written, holding
        ``{"paused_op_kinds": list(paused_op_kinds)}`` -- the same marker shape
        ``write_gate._load_paused_op_kinds`` and the real, build-side
        ``upgrade_reconcile.py`` writer both already use.
    marker_name: the marker file's basename (sans ``.json``) -- irrelevant to
        ``evaluate_write_gate`` (it unions every ``*.json`` marker under ``paused_root``), only
        given a name at all so more than one call in the same test can use distinct marker
        files if ever needed. Never used when ``paused_op_kinds`` is empty (no marker file is
        written at all in that case).

    Always cleans up the temp directory on exit, whether the ``with`` block raised or not.
    """
    tmp_dir = tempfile.mkdtemp(prefix="awb_hermetic_paused_mechanisms_")
    try:
        if paused_op_kinds:
            marker_path = Path(tmp_dir) / f"{marker_name}.json"
            marker_path.write_text(
                json.dumps({"paused_op_kinds": list(paused_op_kinds)}),
                encoding="utf-8",
            )
        yield tmp_dir
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
