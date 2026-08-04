"""The suppressed-invocation tripwire: when the entrypoint pause guard fires,
SOMETHING DURABLE RECORDS IT.

The defect this closes, stated exactly
--------------------------------------
The upgrade's safe-pause inserts a guard into an entrypoint wrapper. The guard
works: it prints ``paused pending migration`` and exits before any payload code,
and that half is not changed here. What did not work is that NOBODY FINDS OUT.
Every scheduled entry redirects ``>> ...log 2>&1``, so the guard's message goes
into a file no operator reads. On a real operator estate that ran NINE TIMES OVER
NINE DAYS -- nine scheduled jobs that silently did not happen -- and the operator
learned nothing.

What is under test here is therefore not "does the guard stop the payload" (it
did) but "is the firing recoverable from disk afterwards".

WHAT THE MECHANISM ESTABLISHES, AND WHAT IT DOES NOT
----------------------------------------------------
Written out because the recurring defect in this area is a claim outrunning its
mechanism.

  ESTABLISHED: the wrapper was invoked and the guard stopped it. An actual
  wrapper invocation is what proves a run was due, which is why this needs no
  cadence model, no output manifest and no liveness monitor.

  NOT ESTABLISHED: that the operator ever SAW it. The record is on disk and the
  session-start health surface reports it; whether anyone looks is outside any
  mechanism here.

  NOT ESTABLISHED: how many SCHEDULED RUNS were suppressed. The count is a count
  of wrapper invocations the guard stopped -- one per invocation, which includes a
  hand invocation and would include a scheduler retry of the same due run. It is
  not a count of scheduled runs due, and the tests below assert it in exactly the
  terms it is recorded in.

  NOT DETECTED AT ALL: an arbitrary missing output, a scheduler that never fired,
  or a payload that ran successfully and silently omitted one of its outputs.
  None of those involve the guard, and none is claimed.

The reach question, which is the whole risk in this task
--------------------------------------------------------
``_safe_pause_entrypoint`` inserts a guard ONLY when the wrapper does not already
carry one, and nothing rewrites an existing guard body. The estate's nine
suppressed runs came from a wrapper paused BEFORE this tripwire existed. So a
tripwire that only reaches wrappers paused AFTER it lands is a mechanism whose
consuming branch never executes on the only population that has ever exhibited
the problem.

``TestReachIntoTheAlreadyPausedPopulation`` is therefore the load-bearing class in
this file: it builds a wrapper carrying the ORIGINAL, historical guard body
(byte-for-byte as this toolkit first generated it) and asserts the tripwire
reaches it -- and that reaching it neither changes what the guard checks nor
touches one byte of the payload. A fixture that only ever exercises a FRESHLY
inserted guard would satisfy the nine-count done-when while the real estate
recorded nothing at all.

Run:  python3 -m unittest discover -s wizard/scripts/lib \\
          -p test_suppressed_invocation_tripwire.py
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_WIZARD = Path(__file__).resolve().parents[2]
_AGENTS_LIB = _WIZARD / "agents" / "lib"
if str(_AGENTS_LIB) not in sys.path:
    sys.path.insert(0, str(_AGENTS_LIB))

from external_write import capability_health          # noqa: E402
from external_write import state_actions              # noqa: E402
from external_write import suppressed_invocation      # noqa: E402
from external_write import writer_state_core          # noqa: E402

import agent_emitter                                  # noqa: E402
import upgrade_reconcile                              # noqa: E402

_RECORDER_SOURCE = (_AGENTS_LIB / "external_write" / "suppressed_invocation.py")

PAUSED_DIR_REL = capability_health.PAUSED_MECHANISMS_DIR_REL
EVENTS_DIR_REL = suppressed_invocation.SUPPRESSED_INVOCATIONS_DIR_REL
MIGRATION_QUEUE_REL = capability_health.MIGRATION_QUEUE_REL


# ---------------------------------------------------------------------------
# The historical guard body, byte-for-byte
#
# Reproduced from this toolkit's FIRST generated guard (the shape every version
# since has generated: the shell tail has never changed, only the comment
# wording). This is the population the estate's nine suppressed runs came from,
# and it is the fixture the reach tests are built on.
# ---------------------------------------------------------------------------

def _historical_guard_block(mechanism_id: str, writer_relpath: str,
                            marker_from_wrapper: str) -> str:
    return (
        f"{upgrade_reconcile._GUARD_BEGIN}\n"
        f"# This entrypoint was safe-paused by the upgrade to v0.11.0 (from "
        f"v0.10.2) because {writer_relpath} was found to change something "
        "outside this project directly, bypassing the external-write safety check.\n"
        "# It stays paused -- and its saved access (credentials) stays untouched -- until\n"
        "# the fix is reviewed and approved through the add-capability flow. A genuinely\n"
        "# separate read-only entrypoint is not affected by this guard.\n"
        '_RECONCILE_HERE="$(cd "$(dirname "$0")" && pwd)"\n'
        f'if [ -e "$_RECONCILE_HERE/{marker_from_wrapper}" ]; then\n'
        '  echo "paused pending migration"\n'
        "  exit 0\n"
        "fi\n"
        f"{upgrade_reconcile._GUARD_END}\n"
        "\n"
    )


_PAYLOAD = (
    "#!/bin/sh\n"
    "# the operator's own wrapper -- every byte below the guard is theirs\n"
    'cd "$(dirname "$0")/.." || exit 1\n'
    'printf "ran\\n" > payload_ran.txt\n'
    'echo "the digest was sent"\n'
)

MECH = "finish_estate_cleanup"
WRITER_REL = "scripts/finish_estate_cleanup.py"
WRAPPER_REL = "scripts/run_finish_estate_cleanup.sh"


class _Project:
    """A temp operator project shaped at the REAL emitted relpaths."""

    def __init__(self, tmp: str) -> None:
        self.root = Path(tmp)

    def write(self, relpath: str, text: str, *, mode: int = 0o644) -> Path:
        p = self.root / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        os.chmod(str(p), mode)
        return p

    def pause_marker(self, mechanism_id: str = MECH) -> Path:
        p = self.root / PAUSED_DIR_REL / f"{mechanism_id}.pause"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
        return p

    def pause_state(self, stem: str = MECH, **overrides) -> Path:
        state = {
            "mechanism_id": stem,
            "writer_relpath": WRITER_REL,
            "entrypoint_relpath": WRAPPER_REL,
            "paused_at": "2026-07-25T09:00:00Z",
            "from_version": "v0.10.2",
            "to_version": "v0.11.0",
            "reason": "external-write gate violation detected on upgrade",
            "violations": [],
            "credentials_preserved": True,
            "migration_status": "pending",
            "paused_content_sha256": "0" * 64,
        }
        state.update(overrides)
        p = self.root / PAUSED_DIR_REL / f"{stem}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n",
                     encoding="utf-8")
        return p

    def install_recorder(self) -> Path:
        """The emitted lib as the guard will actually find it: the ONE module,
        copied to the real emitted relpath. Copied rather than symlinked so the
        wrapper resolves it exactly as an emitted project would."""
        dest = self.root / "agents" / "lib" / "external_write" / "suppressed_invocation.py"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_RECORDER_SOURCE.read_text(encoding="utf-8"),
                        encoding="utf-8")
        return dest

    def historical_wrapper(self, mechanism_id: str = MECH) -> Path:
        marker_ref = upgrade_reconcile._wrapper_guard_marker_ref(
            WRAPPER_REL, mechanism_id)
        guard = _historical_guard_block(mechanism_id, WRITER_REL, marker_ref)
        lines = _PAYLOAD.splitlines(keepends=True)
        return self.write(WRAPPER_REL, lines[0] + guard + "".join(lines[1:]),
                          mode=0o755)

    def event(self, mechanism_id: str = MECH) -> dict:
        path = Path(suppressed_invocation.event_path(str(self.root), mechanism_id))
        return json.loads(path.read_text(encoding="utf-8"))

    def run_wrapper(self, *, env=None, relpath: str = WRAPPER_REL):
        return subprocess.run(
            ["/bin/sh", str(self.root / relpath)],
            capture_output=True, text=True, env=env, cwd=str(self.root))


# ===========================================================================
# 1. The generated guard body
# ===========================================================================

class TestTheGeneratedGuardBody(unittest.TestCase):

    def _block(self):
        return upgrade_reconcile._guard_block(
            MECH, WRITER_REL,
            upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH),
            "v0.22.0", "v0.23.0", WRAPPER_REL)

    def test_the_block_invokes_the_recorder_with_the_declared_identity(self):
        block = self._block()
        self.assertIn(upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL, block)
        # Joined on the DECLARED mechanism_id, never left to be inferred from
        # the marker filename the guard also happens to embed.
        self.assertIn(f"--mechanism-id '{MECH}'", block)
        self.assertIn(f"--entrypoint '{WRAPPER_REL}'", block)

    def test_the_exit_is_unconditional_and_never_chained_to_the_recorder(self):
        block = self._block()
        lines = block.splitlines()
        recorder_idx = [i for i, l in enumerate(lines)
                        if upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL in l]
        self.assertEqual(len(recorder_idx), 1, block)
        # `... && exit 0` is the shape that falls through to the payload when the
        # recorder fails. The exit must be its own statement.
        self.assertNotIn("&& exit", block)
        self.assertIn(upgrade_reconcile._GUARD_EXIT_LINE, lines)
        # ...and it must come AFTER the recorder, still inside the `if`.
        self.assertLess(recorder_idx[0],
                        lines.index(upgrade_reconcile._GUARD_EXIT_LINE))

    def test_the_recorder_status_is_neutralised_so_set_e_cannot_pre_empt_the_exit(self):
        block = self._block()
        recorder_stmt = [l for l in block.splitlines()
                         if l.strip().endswith("|| :")]
        self.assertTrue(recorder_stmt,
                        "the recorder invocation must end `|| :` -- under `sh -e` a "
                        "nonzero recorder would otherwise abort the wrapper before "
                        f"the unconditional exit ran.\n{block}")

    def test_the_recorder_may_not_write_to_the_wrappers_stdout(self):
        self.assertIn(">/dev/null", self._block())

    def test_the_guard_still_prints_the_shipped_message_and_the_marker_check(self):
        block = self._block()
        self.assertIn(upgrade_reconcile._GUARD_PAUSED_ECHO_LINE, block.splitlines())
        self.assertIn(
            f'if [ -e "$_RECONCILE_HERE/'
            f'{upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH)}" ]; then',
            block)

    def test_a_single_quote_in_an_identity_is_escaped_not_dropped(self):
        block = upgrade_reconcile._guard_block(
            "o'brien", WRITER_REL, "../x.pause", "a", "b", "scripts/run_o'brien.sh")
        self.assertIn("""'o'\\''brien'""", block)
        self.assertIn("""'scripts/run_o'\\''brien.sh'""", block)


# ===========================================================================
# 2. Recorder failure PROVABLY cannot run the payload
# ===========================================================================

class TestRecorderFailureCannotRunThePayload(unittest.TestCase):
    """Behavioural, through /bin/sh, on a real wrapper -- the only way to
    establish this. Every case asserts the payload's own side effect is ABSENT."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.p.historical_wrapper()
        upgrade_reconcile.upgrade_paused_entrypoint_guards  # API presence
        self.p.pause_marker()
        self.p.pause_state()
        self.p.write(WRITER_REL, "# flagged writer\n")

    def _sweep(self):
        return upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)

    def _assert_payload_did_not_run(self, proc):
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("paused pending migration", proc.stdout)
        self.assertFalse((self.p.root / "payload_ran.txt").exists(),
                         "the payload RAN behind a fired guard")
        self.assertNotIn("the digest was sent", proc.stdout)

    def test_the_recorder_module_being_absent_does_not_run_the_payload(self):
        self._sweep()
        # No recorder installed at all: `python3 <missing>` exits nonzero.
        self._assert_payload_did_not_run(self.p.run_wrapper())

    def test_no_python3_on_path_does_not_run_the_payload(self):
        """The scheduler's environment, not an activated venv: a bare ``python3``
        may be a different interpreter than the project's, or absent entirely.

        Modelled by a PATH carrying the utilities the SHIPPED guard body already
        needs but no ``python3`` -- rather than an empty PATH, which would instead
        exercise the guard's own pre-existing dependence on ``dirname`` and prove
        nothing about the recorder."""
        self._sweep()
        self.p.install_recorder()
        bindir = self.p.root / "fakebin"
        bindir.mkdir()
        for tool in ("dirname", "basename", "env"):
            for candidate in (Path("/usr/bin") / tool, Path("/bin") / tool):
                if candidate.exists():
                    os.symlink(str(candidate), str(bindir / tool))
                    break
        self.assertTrue((bindir / "dirname").exists(), "no dirname to link")
        env = dict(os.environ, PATH=str(bindir))
        self._assert_payload_did_not_run(self.p.run_wrapper(env=env))

    def test_a_recorder_that_raises_does_not_run_the_payload(self):
        self._sweep()
        dest = self.p.install_recorder()
        dest.write_text("raise SystemExit(7)\n", encoding="utf-8")
        self._assert_payload_did_not_run(self.p.run_wrapper())

    def test_a_recorder_that_cannot_write_does_not_run_the_payload(self):
        self._sweep()
        self.p.install_recorder()
        events = self.p.root / EVENTS_DIR_REL
        events.mkdir(parents=True, exist_ok=True)
        os.chmod(str(events), 0o500)
        self.addCleanup(os.chmod, str(events), 0o700)
        self._assert_payload_did_not_run(self.p.run_wrapper())

    def test_a_freshly_paused_wrapper_also_stops_the_payload(self):
        """Through ``_safe_pause_entrypoint`` -- the OTHER guard-body producer.

        Every other case in this class reaches the guard through the insertion
        sweep, so without this one the freshly-generated body's own exit is
        asserted only structurally. Two producers of one guard shape need two
        behavioural proofs; a mutation removing the generated exit was invisible
        to this class until this test existed."""
        self.p.write(WRAPPER_REL, _PAYLOAD, mode=0o755)
        upgrade_reconcile._safe_pause_entrypoint(
            self.p.root, MECH, WRITER_REL, WRAPPER_REL, [], "v0.22.0", "v0.23.0")
        self.assertIn(upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
                      (self.p.root / WRAPPER_REL).read_text(encoding="utf-8"))
        # No recorder installed: the recorder call fails and must change nothing.
        self._assert_payload_did_not_run(self.p.run_wrapper())

    def test_under_sh_dash_e_a_failing_recorder_still_reaches_the_exit(self):
        """``sh -e`` is the case ``|| :`` exists for: without it, a nonzero
        recorder aborts the wrapper BEFORE the unconditional exit runs. The
        payload is still not reached either way -- but the wrapper's own exit
        status becomes the recorder's, which is a scheduled job reporting a
        failure for the wrong reason."""
        self._sweep()
        # No recorder module installed -> `python3 <missing>` exits nonzero.
        proc = subprocess.run(["/bin/sh", "-e", str(self.p.root / WRAPPER_REL)],
                              capture_output=True, text=True, cwd=str(self.p.root))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("paused pending migration", proc.stdout)
        self.assertFalse((self.p.root / "payload_ran.txt").exists())

    def test_the_payload_runs_normally_when_the_marker_is_absent(self):
        """The control. Without this, every assertion above is satisfiable by a
        wrapper that is simply broken."""
        self._sweep()
        self.p.install_recorder()
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.pause").unlink()
        proc = self.p.run_wrapper()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.p.root / "payload_ran.txt").exists())
        self.assertIn("the digest was sent", proc.stdout)
        self.assertNotIn("paused pending migration", proc.stdout)


# ===========================================================================
# 3. Reach into the already-paused population -- THE load-bearing class
# ===========================================================================

class TestReachIntoTheAlreadyPausedPopulation(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.before = self.p.historical_wrapper().read_text(encoding="utf-8")
        self.p.pause_marker()
        self.p.pause_state()
        self.p.write(WRITER_REL, "# flagged writer\n")

    def _wrapper_text(self):
        return (self.p.root / WRAPPER_REL).read_text(encoding="utf-8")

    def _outside_the_guard(self, text):
        head, _, rest = text.partition(upgrade_reconcile._GUARD_BEGIN)
        _, _, tail = rest.partition(upgrade_reconcile._GUARD_END)
        return head, tail

    def test_a_wrapper_carrying_the_historical_guard_gains_the_tripwire(self):
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [MECH], report)
        self.assertIn(upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
                      self._wrapper_text())

    def test_the_operators_own_payload_is_byte_identical_afterwards(self):
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(self._outside_the_guard(self.before),
                         self._outside_the_guard(self._wrapper_text()))

    def test_the_marker_check_the_guard_pauses_on_is_byte_identical_afterwards(self):
        """The whole risk of touching an existing guard: a rewrite that changes
        what the `-e` test looks at silently UN-PAUSES a live writer."""
        marker_line = [l for l in self.before.splitlines() if "[ -e " in l]
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(
            marker_line,
            [l for l in self._wrapper_text().splitlines() if "[ -e " in l])

    def test_the_upgraded_guard_still_stops_the_payload(self):
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.p.install_recorder()
        proc = self.p.run_wrapper()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((self.p.root / "payload_ran.txt").exists())

    def test_the_historical_guards_own_comment_lines_are_left_alone(self):
        """Deliberately the SMALLEST possible change to a wrapper on the
        fail-closed pause-safety path: one line inserted, nothing rewritten. It
        also means this sweep does not quietly overwrite the historical notice
        wording a separate correction pass owns."""
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        for line in self.before.splitlines():
            if line.startswith("# ") and "safe-paused" in line:
                self.assertIn(line, self._wrapper_text().splitlines())

    def test_nine_real_wrapper_invocations_of_a_historically_paused_wrapper_report_nine(self):
        """The estate's shape, reproduced end to end: a wrapper paused BEFORE
        this tripwire existed, invoked nine times. Nine is asserted from nine
        real ``/bin/sh`` invocations, never from nine direct recorder calls --
        a fixture that called the recorder directly would prove the arithmetic
        and say nothing about reach."""
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.p.install_recorder()
        for _ in range(9):
            proc = self.p.run_wrapper()
            self.assertEqual(proc.returncode, 0, proc.stderr)
        event = self.p.event()
        self.assertEqual(event["suppressed_count"], 9)
        self.assertEqual(event["mechanism_id"], MECH)
        self.assertEqual(event["entrypoint_relpath"], WRAPPER_REL)
        self.assertLessEqual(event["first_suppressed_at"],
                             event["last_suppressed_at"])
        self.assertFalse((self.p.root / "payload_ran.txt").exists())

    def test_the_record_lands_in_the_project_when_invoked_from_another_directory(self):
        """A scheduler does not run the wrapper from the project root -- cron runs
        with the home directory as its working directory. Every path the guard
        hands over is derived from the wrapper's OWN location, so the record must
        land in the project regardless of where it was invoked from. Asserted from
        a different cwd, because every other invocation in this file runs from the
        root and would pass on a cwd-relative path just as well."""
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.p.install_recorder()
        with tempfile.TemporaryDirectory() as elsewhere:
            proc = subprocess.run(
                ["/bin/sh", str(self.p.root / WRAPPER_REL)],
                capture_output=True, text=True, cwd=elsewhere)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(list(Path(elsewhere).iterdir()), [],
                             "the record was written next to the caller, not the project")
        self.assertEqual(self.p.event()["suppressed_count"], 1)
        self.assertEqual(
            self.p.event()["known_entangled_outputs"]["determination"],
            suppressed_invocation.ENTANGLEMENT_UNKNOWN,
            "the pause-state path the guard hands over must also resolve from "
            "the wrapper's own location")

    def test_the_pause_state_the_guard_points_at_resolves_from_the_wrapper(self):
        """The labels only reach the record if the ``--pause-state`` path the guard
        embeds actually resolves. Proven by making the determination one that
        CANNOT arise by default: `unknown` is what an unresolvable path yields, so
        a test asserting `unknown` would pass on a broken path."""
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
            json.dumps({"mechanism_id": MECH, "writer_relpath": WRITER_REL,
                        "entrypoint_relpath": WRAPPER_REL,
                        "carries_read_outputs": True,
                        "entangled_read_outputs": ["digest", "backup"]},
                       indent=2, sort_keys=True) + "\n", encoding="utf-8")
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.p.install_recorder()
        self.assertEqual(self.p.run_wrapper().returncode, 0)
        entangled = self.p.event()["known_entangled_outputs"]
        self.assertEqual(entangled["determination"],
                         suppressed_invocation.ENTANGLEMENT_ENTANGLED)
        self.assertEqual(entangled["labels"], ["digest", "backup"])

    def test_the_sweep_is_idempotent_and_does_not_rewrite_a_current_guard(self):
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        after_first = self._wrapper_text()
        stat_before = os.stat(str(self.p.root / WRAPPER_REL))
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["already_current"], [MECH], report)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(after_first, self._wrapper_text())
        self.assertEqual(stat_before.st_mtime_ns,
                         os.stat(str(self.p.root / WRAPPER_REL)).st_mtime_ns)

    def test_the_wrappers_executable_bit_survives(self):
        upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertTrue(os.access(str(self.p.root / WRAPPER_REL), os.X_OK))

    def test_a_guard_naming_a_different_marker_is_refused_untouched(self):
        """A guard whose embedded marker reference this sweep cannot reconstruct
        is one whose pause semantics it does not understand. It is left exactly
        as it is: a missing count is far cheaper than an un-paused writer."""
        text = self._wrapper_text().replace(
            upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH),
            "../.wizard/paused-mechanisms/some_other_id.pause")
        self.p.write(WRAPPER_REL, text, mode=0o755)
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [MECH])
        self.assertEqual(text, self._wrapper_text())

    def test_two_guard_blocks_in_one_wrapper_are_refused_untouched(self):
        text = self._wrapper_text()
        doubled = text + "\n" + text
        self.p.write(WRAPPER_REL, doubled, mode=0o755)
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [MECH])
        self.assertEqual(doubled, self._wrapper_text())

    def test_a_guard_with_no_recognisable_paused_message_line_is_refused(self):
        text = self._wrapper_text().replace(
            upgrade_reconcile._GUARD_PAUSED_ECHO_LINE, '  echo "halted"')
        self.p.write(WRAPPER_REL, text, mode=0o755)
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(text, self._wrapper_text())

    def test_a_wrapper_with_no_guard_at_all_is_skipped_not_gated(self):
        self.p.write(WRAPPER_REL, _PAYLOAD, mode=0o755)
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(_PAYLOAD, self._wrapper_text())

    def test_a_state_whose_declared_id_disagrees_with_its_filename_is_refused(self):
        """Identity is the DECLARED value. A filename is a candidate, and a
        disagreement is reported rather than resolved by picking one."""
        self.p.pause_state(MECH, mechanism_id="something_else")
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertTrue(report["refused"])
        self.assertEqual(self.before, self._wrapper_text())

    def test_a_paused_live_write_state_with_no_entrypoint_is_skipped(self):
        self.p.pause_state(MECH, entrypoint_relpath=None,
                           state="paused_live_write")
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(report["refused"], [])
        self.assertEqual(self.before, self._wrapper_text())

    def test_an_absent_marker_directory_is_not_an_error(self):
        """A project that never paused anything is the overwhelmingly common
        case -- including every fresh build. It must report nothing."""
        with tempfile.TemporaryDirectory() as t:
            report = upgrade_reconcile.upgrade_paused_entrypoint_guards(Path(t))
            self.assertEqual(report["upgraded"], [])
            self.assertIsNone(report["scan_error"])

    def test_an_inaccessible_marker_directory_is_a_scan_error_not_silence(self):
        d = self.p.root / PAUSED_DIR_REL
        os.chmod(str(d), 0o000)
        self.addCleanup(os.chmod, str(d), 0o700)
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertIsNotNone(report["scan_error"])

    def test_an_unparseable_state_record_is_reported_not_skipped_silently(self):
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
            "{not json", encoding="utf-8")
        report = upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p.root)
        self.assertTrue(report["refused"])


class TestTheInsertionPostCondition(unittest.TestCase):
    """The whole-file post-condition, tested against its CONTRACT rather than only
    through the happy path.

    Why it needs its own class. In the ordinary flow the construction genuinely
    only inserts, so disabling this check changes nothing observable -- a mutation
    that removed it passed the entire behavioural battery. It is a backstop against
    a future change to the construction above it, and the only way to falsify a
    backstop is to hand it the input it exists to reject. What it rejects is
    precisely the thing that would silently un-pause a live writer."""

    ORIGINAL = (
        "#!/bin/sh\n"
        f"{upgrade_reconcile._GUARD_BEGIN}\n"
        '_RECONCILE_HERE="$(cd "$(dirname "$0")" && pwd)"\n'
        f'if [ -e "$_RECONCILE_HERE/'
        f'{upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH)}" ]; then\n'
        f"{upgrade_reconcile._GUARD_PAUSED_ECHO_LINE}\n"
        f"{upgrade_reconcile._GUARD_EXIT_LINE}\n"
        "fi\n"
        f"{upgrade_reconcile._GUARD_END}\n"
        'printf "ran\\n" > payload_ran.txt\n'
    )

    def _lines(self):
        return upgrade_reconcile._guard_recorder_lines(MECH, WRAPPER_REL)

    def _problem(self, candidate):
        return upgrade_reconcile._tripwire_insertion_problem(
            self.ORIGINAL, candidate, WRAPPER_REL, MECH)

    def _insertion_only(self):
        anchor = f"{upgrade_reconcile._GUARD_PAUSED_ECHO_LINE}\n"
        return self.ORIGINAL.replace(anchor, anchor + self._lines())

    def test_the_insertion_only_candidate_is_accepted(self):
        """The positive control. Without it, a post-condition that refused
        EVERYTHING would look just as good as one that works."""
        self.assertIsNone(self._problem(self._insertion_only()))

    def test_a_candidate_that_also_changes_the_payload_is_refused(self):
        candidate = self._insertion_only().replace(
            'printf "ran\\n" > payload_ran.txt', 'printf "nope\\n"')
        self.assertIsNotNone(self._problem(candidate))

    def test_a_candidate_that_also_changes_the_marker_reference_is_refused(self):
        """THE hazard this whole design is arranged around: a guard that checks a
        marker path which no longer exists finds nothing, and the writer silently
        resumes."""
        candidate = self._insertion_only().replace(
            upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH),
            "../.wizard/paused-mechanisms/moved.pause")
        self.assertIsNotNone(self._problem(candidate))

    def test_a_candidate_that_also_drops_the_exit_is_refused(self):
        candidate = self._insertion_only().replace(
            f"{upgrade_reconcile._GUARD_EXIT_LINE}\n", "")
        self.assertIsNotNone(self._problem(candidate))

    def test_a_candidate_placing_the_lines_after_the_exit_is_refused(self):
        anchor = f"{upgrade_reconcile._GUARD_EXIT_LINE}\n"
        candidate = self.ORIGINAL.replace(anchor, anchor + self._lines())
        self.assertIsNotNone(self._problem(candidate))

    def test_a_candidate_that_also_adds_a_second_guard_block_is_refused(self):
        candidate = self._insertion_only() + upgrade_reconcile._GUARD_BEGIN + "\n"
        self.assertIsNotNone(self._problem(candidate))


class TestTheSweepIsOnTheEnforcedPath(unittest.TestCase):
    """No zero-caller mechanism: the real upgrade flow must run the sweep, and
    it must reach a mechanism this pass did NOT re-flag (a writer whose file is
    gone or quarantined still has a live, guard-paused wrapper)."""

    WRITER = "agents/cron/estate_upkeep.py"
    WRAPPER = "agents/cron/run_estate_upkeep.sh"
    MECHANISM = "estate_upkeep"

    def test_the_whole_thing_end_to_end_through_the_real_upgrade_entrypoint(self):
        """One assertion chain, driven ONLY by ``reconcile_upgrade`` and ``/bin/sh``.

        Nothing here calls the pause helper, the sweep, the recorder or the health
        surface's inputs directly: the upgrade runs, the operator's own wrapper is
        invoked twice, and the session-start surface is asked what it sees. That is
        the whole mechanism, verified through the producer's real entrypoint rather
        than through a hand-built stand-in of it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            p = _Project(tmp)
            # A scanner-RED writer that is ALSO the thing producing a digest -- the
            # estate's actual shape, and what makes the entanglement labels real.
            p.write(self.WRITER,
                    '"""Nightly estate upkeep: sends the digest, then writes back."""\n'
                    "from external_write.run_envelope import mint_run_envelope\n")
            p.write(self.WRAPPER,
                    "#!/bin/sh\n"
                    'cd "$(dirname "$0")/../.." || exit 1\n'
                    'printf "ran\\n" > payload_ran.txt\n',
                    mode=0o755)
            p.install_recorder()

            upgrade_reconcile.reconcile_upgrade(
                p.root, _WIZARD.parent, from_version="v0.22.0",
                to_version="v0.23.0")

            # 1. It was paused, and the wrapper carries the tripwire.
            wrapper_text = (p.root / self.WRAPPER).read_text(encoding="utf-8")
            self.assertIn(upgrade_reconcile._GUARD_BEGIN, wrapper_text)
            self.assertIn(upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
                          wrapper_text)

            # 2. Two invocations, as a schedule would make them.
            for _ in range(2):
                proc = p.run_wrapper(relpath=self.WRAPPER)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("paused pending migration", proc.stdout)
            self.assertFalse((p.root / "payload_ran.txt").exists())

            # 3. The record, with the labels reconcile derived.
            event = p.event(self.MECHANISM)
            self.assertEqual(event["suppressed_count"], 2)
            self.assertEqual(event["entrypoint_relpath"], self.WRAPPER)
            self.assertEqual(
                event["known_entangled_outputs"]["determination"],
                suppressed_invocation.ENTANGLEMENT_ENTANGLED)
            self.assertIn("digest", event["known_entangled_outputs"]["labels"])

            # 4. What the operator's assistant sees at session start.
            status = capability_health.overall_status(str(p.root))
            self.assertFalse(status["normal_status_allowed"], status)
            surfaced = status["suppressed_invocations"]
            self.assertTrue(surfaced["active"])
            (entry,) = surfaced["mechanisms"]
            self.assertEqual(entry["mechanism_id"], self.MECHANISM)
            self.assertEqual(entry["suppressed_count"], 2)
            self.assertTrue(entry["read_outputs_may_be_suppressed"])
            # A REAL way out, byte-equal to the registry's own rendering for the
            # state this writer is actually in -- not merely a non-empty string, and
            # not the registry's route-to-a-person fallback. An active suppression
            # with no performable exit is the dead-end shape this cut exists to
            # remove; asserting only "non-empty" would pass on that fallback.
            writer_state = status["open_external_write_bypass"]["writer_states"][
                self.WRITER]
            self.assertEqual(
                entry["action"],
                state_actions.instruction_for_state(
                    state_actions.writer_state_key(writer_state), self.WRITER))
            self.assertNotEqual(
                entry["action"],
                state_actions.route_for_unclassified_state(self.WRAPPER))
            self.assertEqual(writer_state,
                             writer_state_core.WriterState.BLOCKING_LIVE_ENABLE)

    def test_reconcile_upgrade_upgrades_a_guard_it_did_not_pause_this_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _Project(tmp)
            p.historical_wrapper()
            p.pause_marker()
            p.pause_state()
            # NO writer file on disk -- so the scanner cannot flag it and the
            # per-mechanism loop never reaches this wrapper at all.
            upgrade_reconcile.reconcile_upgrade(
                p.root, _WIZARD.parent, from_version="v0.22.0",
                to_version="v0.23.0")
            self.assertIn(upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
                          (p.root / WRAPPER_REL).read_text(encoding="utf-8"))


# ===========================================================================
# 4. The durable event
# ===========================================================================

class TestTheDurableEvent(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _record(self, **kw):
        kw.setdefault("project_root", str(self.p.root))
        kw.setdefault("mechanism_id", MECH)
        kw.setdefault("entrypoint_relpath", WRAPPER_REL)
        return suppressed_invocation.record_suppressed_invocation(**kw)

    def test_the_first_event_carries_every_declared_field(self):
        event = self._record()
        for key in ("schema", "mechanism_id", "entrypoint_relpath",
                    "first_suppressed_at", "last_suppressed_at",
                    "suppressed_count", "known_entangled_outputs"):
            self.assertIn(key, event)
        self.assertEqual(event["schema"],
                         suppressed_invocation.SUPPRESSED_INVOCATION_SCHEMA)
        self.assertEqual(event["suppressed_count"], 1)
        self.assertEqual(event["first_suppressed_at"], event["last_suppressed_at"])

    def test_the_event_is_json_serialisable_by_a_real_round_trip(self):
        event = self._record()
        self.assertEqual(json.loads(json.dumps(event)), event)

    def test_the_count_increments_and_the_first_timestamp_is_preserved(self):
        first = self._record()
        time.sleep(1.01)
        second = self._record()
        self.assertEqual(second["suppressed_count"], 2)
        self.assertEqual(second["first_suppressed_at"], first["first_suppressed_at"])
        self.assertGreater(second["last_suppressed_at"], first["last_suppressed_at"])

    def test_a_malformed_event_is_refused_never_silently_reset_to_one(self):
        """A silent reset to 1 would UNDER-REPORT the exact harm this exists to
        surface -- nine suppressed runs would read as one."""
        path = Path(suppressed_invocation.event_path(str(self.p.root), MECH))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{truncated", encoding="utf-8")
        with self.assertRaises(suppressed_invocation.SuppressedInvocationError):
            self._record()
        self.assertEqual("{truncated", path.read_text(encoding="utf-8"))

    def test_an_event_recorded_under_a_different_id_is_refused(self):
        path = Path(suppressed_invocation.event_path(str(self.p.root), MECH))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema": suppressed_invocation.SUPPRESSED_INVOCATION_SCHEMA,
            "mechanism_id": "someone_else", "entrypoint_relpath": WRAPPER_REL,
            "first_suppressed_at": "2026-01-01T00:00:00Z",
            "last_suppressed_at": "2026-01-01T00:00:00Z",
            "suppressed_count": 3,
            "known_entangled_outputs": {
                "determination": suppressed_invocation.ENTANGLEMENT_UNKNOWN,
                "labels": []},
        }) + "\n", encoding="utf-8")
        with self.assertRaises(suppressed_invocation.SuppressedInvocationError):
            self._record()

    def test_an_unusable_mechanism_id_is_validated_never_rewritten(self):
        for bad in ("../escape", "a/b", ".hidden", "", "."):
            with self.assertRaises(suppressed_invocation.SuppressedInvocationError):
                self._record(mechanism_id=bad)

    def test_concurrent_recorders_do_not_lose_a_count(self):
        self.p.install_recorder()
        procs = [
            subprocess.Popen(
                [sys.executable,
                 str(self.p.root / "agents/lib/external_write/suppressed_invocation.py"),
                 "record", "--mechanism-id", MECH, "--entrypoint", WRAPPER_REL,
                 "--project-root", str(self.p.root)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(8)]
        for pr in procs:
            pr.communicate()
            self.assertEqual(pr.returncode, 0)
        self.assertEqual(self.p.event()["suppressed_count"], 8)

    def test_an_inaccessible_event_file_is_not_read_as_never_suppressed(self):
        self._record()
        path = Path(suppressed_invocation.event_path(str(self.p.root), MECH))
        os.chmod(str(path), 0o000)
        self.addCleanup(os.chmod, str(path), 0o600)
        with self.assertRaises(suppressed_invocation.SuppressedInvocationError):
            self._record()

    def test_a_record_whose_own_stat_fails_is_not_read_as_never_suppressed(self):
        """Isolates the ``os.stat`` handler, which nothing else reaches.

        The chmod-000 case above is caught one line later by ``open``, so a
        mutation collapsing ``FileNotFoundError`` into a bare ``except OSError``
        there survived the whole battery -- a real control that looked
        unfalsifiable only because no test put it on the only path that reaches
        it. A self-referential symlink is such a path: ``stat`` raises ELOOP while
        ``listdir`` still reports the name, so "absent" and "cannot be examined"
        are genuinely different answers about the same file."""
        path = Path(suppressed_invocation.event_path(str(self.p.root), MECH))
        path.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(path.name, str(path))
        with self.assertRaises(suppressed_invocation.SuppressedInvocationError):
            self._record()
        scan = suppressed_invocation.scan_suppressed_invocation_events(
            directory=str(path.parent))
        self.assertEqual(scan["events"], [])
        self.assertEqual([u["path"] for u in scan["unreadable"]], [str(path)])

    def test_the_recorder_waits_for_the_lock_only_briefly(self):
        """A recorder that hangs never runs the payload (safe) but hangs the
        scheduled job. The wait is bounded, and exhausting it REFUSES rather
        than writing an unlocked read-modify-write."""
        import fcntl
        self.p.install_recorder()
        lock = Path(suppressed_invocation.lock_path(str(self.p.root), MECH))
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(str(lock), "w", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            started = time.time()
            proc = subprocess.run(
                [sys.executable,
                 str(self.p.root / "agents/lib/external_write/suppressed_invocation.py"),
                 "record", "--mechanism-id", MECH, "--entrypoint", WRAPPER_REL,
                 "--project-root", str(self.p.root)],
                capture_output=True, text=True)
            waited = time.time() - started
        self.assertNotEqual(proc.returncode, 0)
        self.assertLess(waited, suppressed_invocation.LOCK_WAIT_SECONDS + 5.0)
        self.assertIn(suppressed_invocation.SUPPRESSED_INVOCATION_SCHEMA,
                      proc.stderr)


class TestTheStructuredStderr(unittest.TestCase):
    """Structured stderr is a CONVENIENCE for someone already reading the log
    that already swallowed nine days of this message -- never the delivery. It
    is tested for shape, and for not polluting the wrapper's stdout."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.p.install_recorder()

    def _cli(self, *args):
        return subprocess.run(
            [sys.executable,
             str(self.p.root / "agents/lib/external_write/suppressed_invocation.py"),
             *args], capture_output=True, text=True)

    def test_a_successful_record_prints_one_json_object_on_stderr_and_nothing_on_stdout(self):
        proc = self._cli("record", "--mechanism-id", MECH,
                         "--entrypoint", WRAPPER_REL,
                         "--project-root", str(self.p.root))
        self.assertEqual(proc.returncode, suppressed_invocation.EXIT_RECORDED)
        self.assertEqual(proc.stdout, "")
        payload = json.loads(proc.stderr.strip())
        self.assertEqual(payload["schema"],
                         suppressed_invocation.SUPPRESSED_INVOCATION_SCHEMA)
        self.assertEqual(payload["suppressed_count"], 1)

    def test_an_unrecognised_flag_refuses_rather_than_being_dropped(self):
        proc = self._cli("record", "--mechanism-id", MECH,
                         "--entrypoint", WRAPPER_REL,
                         "--project-root", str(self.p.root), "--wat")
        self.assertEqual(proc.returncode, suppressed_invocation.EXIT_BAD_ARGS)
        self.assertFalse(
            Path(suppressed_invocation.event_path(str(self.p.root), MECH)).exists())

    def test_a_failure_reports_on_stderr_with_a_nonzero_status(self):
        path = Path(suppressed_invocation.event_path(str(self.p.root), MECH))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{truncated", encoding="utf-8")
        proc = self._cli("record", "--mechanism-id", MECH,
                         "--entrypoint", WRAPPER_REL,
                         "--project-root", str(self.p.root))
        self.assertEqual(proc.returncode, suppressed_invocation.EXIT_NOT_RECORDED)
        self.assertEqual(proc.stdout, "")
        self.assertIn(suppressed_invocation.SUPPRESSED_INVOCATION_SCHEMA,
                      proc.stderr)


# ===========================================================================
# 5. The entangled-output labels, including the UNKNOWN case
# ===========================================================================

class TestTheEntangledOutputLabels(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _record(self, pause_state=None):
        return suppressed_invocation.record_suppressed_invocation(
            project_root=str(self.p.root), mechanism_id=MECH,
            entrypoint_relpath=WRAPPER_REL,
            pause_state_path=(str(pause_state) if pause_state else None))

    def test_labels_reconcile_derived_are_carried_onto_the_event(self):
        state = self.p.pause_state(carries_read_outputs=True,
                                   entangled_read_outputs=["digest", "backup"])
        event = self._record(state)
        self.assertEqual(event["known_entangled_outputs"]["determination"],
                         suppressed_invocation.ENTANGLEMENT_ENTANGLED)
        self.assertEqual(event["known_entangled_outputs"]["labels"],
                         ["digest", "backup"])

    def test_an_absent_pause_state_records_unknown_not_absence(self):
        event = self._record(self.p.root / PAUSED_DIR_REL / "nope.json")
        self.assertEqual(event["known_entangled_outputs"]["determination"],
                         suppressed_invocation.ENTANGLEMENT_UNKNOWN)

    def test_an_unverified_pause_state_records_unknown_not_absence(self):
        state = self.p.pause_state(carries_read_outputs=None,
                                   entangled_read_outputs=[])
        event = self._record(state)
        self.assertEqual(event["known_entangled_outputs"]["determination"],
                         suppressed_invocation.ENTANGLEMENT_UNKNOWN)

    def test_an_unreadable_pause_state_records_unknown_not_absence(self):
        state = self.p.pause_state(carries_read_outputs=True,
                                   entangled_read_outputs=["digest"])
        state.write_text("{nope", encoding="utf-8")
        event = self._record(state)
        self.assertEqual(event["known_entangled_outputs"]["determination"],
                         suppressed_invocation.ENTANGLEMENT_UNKNOWN)

    def test_a_positively_verified_companion_records_separate_verified(self):
        state = self.p.pause_state(
            carries_read_outputs=False,
            separate_readonly_entrypoint="scripts/run_finish_estate_cleanup_digest.sh",
            entangled_read_outputs=[])
        event = self._record(state)
        self.assertEqual(event["known_entangled_outputs"]["determination"],
                         suppressed_invocation.ENTANGLEMENT_SEPARATE_VERIFIED)

    def test_carries_read_outputs_false_with_NO_verified_companion_is_unknown(self):
        """Deny-by-default: `False` alone is not a continuity claim -- the
        notice layer requires a positively verified companion, and so does
        this."""
        state = self.p.pause_state(carries_read_outputs=False,
                                   separate_readonly_entrypoint=None,
                                   entangled_read_outputs=[])
        event = self._record(state)
        self.assertEqual(event["known_entangled_outputs"]["determination"],
                         suppressed_invocation.ENTANGLEMENT_UNKNOWN)

    def test_unknown_is_treated_exactly_like_entangled_by_the_one_classifier(self):
        self.assertTrue(suppressed_invocation.read_outputs_may_be_suppressed(
            suppressed_invocation.ENTANGLEMENT_ENTANGLED))
        self.assertTrue(suppressed_invocation.read_outputs_may_be_suppressed(
            suppressed_invocation.ENTANGLEMENT_UNKNOWN))
        self.assertFalse(suppressed_invocation.read_outputs_may_be_suppressed(
            suppressed_invocation.ENTANGLEMENT_SEPARATE_VERIFIED))
        # An unrecognised value fails toward "may be dark".
        self.assertTrue(
            suppressed_invocation.read_outputs_may_be_suppressed("something-new"))

    def test_a_known_entanglement_is_never_downgraded_by_a_later_unknown(self):
        """Silence is not evidence of absence: once labels are known, a later
        read that cannot establish them must not erase them."""
        state = self.p.pause_state(carries_read_outputs=True,
                                   entangled_read_outputs=["digest"])
        self._record(state)
        event = self._record(None)
        self.assertEqual(event["known_entangled_outputs"]["determination"],
                         suppressed_invocation.ENTANGLEMENT_ENTANGLED)
        self.assertEqual(event["known_entangled_outputs"]["labels"], ["digest"])

    def test_reconcile_threads_the_labels_it_derives_into_the_pause_state(self):
        """The pause state ``_safe_pause_entrypoint`` writes carries no entangled
        labels at all, and ``_guard_block`` is not passed them either -- so the
        thread has to exist somewhere. Here."""
        upgrade_reconcile._record_pause_entanglement(
            self.p.root, MECH, True, ["digest", "alert"])
        # The state file did not exist: nothing is fabricated.
        self.assertFalse((self.p.root / PAUSED_DIR_REL / f"{MECH}.json").exists())
        self.p.pause_state()
        upgrade_reconcile._record_pause_entanglement(
            self.p.root, MECH, True, ["digest", "alert"])
        state = json.loads(
            (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").read_text(encoding="utf-8"))
        self.assertIs(state["carries_read_outputs"], True)
        self.assertEqual(state["entangled_read_outputs"], ["digest", "alert"])
        # Every field the pause state already carried survives.
        self.assertEqual(state["paused_content_sha256"], "0" * 64)
        self.assertEqual(state["migration_status"], "pending")


# ===========================================================================
# 6. The health surface
# ===========================================================================

class TestTheHealthSurface(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _suppress(self, count=1, **state_kw):
        state = self.p.pause_state(**state_kw) if state_kw else self.p.pause_state()
        self.p.pause_marker()
        for _ in range(count):
            suppressed_invocation.record_suppressed_invocation(
                project_root=str(self.p.root), mechanism_id=MECH,
                entrypoint_relpath=WRAPPER_REL, pause_state_path=str(state))

    def _queue(self, state_kind="blocking"):
        """An open bespoke-writer migration entry, so the writer has a DECLARED
        state the registry can be keyed on."""
        self.p.write(WRITER_REL,
                     "from external_write.run_envelope import mint_run_envelope\n")
        entry = {
            "mechanism_id": MECH, "writer_relpath": WRITER_REL,
            "entrypoint_relpath": WRAPPER_REL, "status": "pending",
            "requested_at": "2026-07-25T09:00:00Z",
            "from_version": "v0.10.2", "to_version": "v0.11.0",
            "violations": [{"path": WRITER_REL, "line": 1,
                            "kind": "adapter_module_import"}],
            "paused_content_sha256": "0" * 64,
        }
        self.p.write(MIGRATION_QUEUE_REL, json.dumps([entry], indent=2) + "\n")

    def _status(self):
        return capability_health.overall_status(str(self.p.root))

    def test_a_fresh_project_with_nothing_paused_stays_green(self):
        """Quantified over the DECLARED set -- the recorded events -- never over
        everything registered. A check that fires on every deployment, including
        every fresh build, is worse than no check."""
        status = self._status()
        self.assertTrue(status["normal_status_allowed"], status)
        self.assertFalse(status["suppressed_invocations"]["active"])
        self.assertEqual(status["suppressed_invocations"]["mechanisms"], [])
        self.assertIsNone(status["suppressed_invocations"]["scan_error"])

    def test_active_suppression_withholds_the_all_clear(self):
        self._suppress(9)
        status = self._status()
        self.assertFalse(status["normal_status_allowed"], status)
        self.assertTrue(status["suppressed_invocations"]["active"])
        (entry,) = status["suppressed_invocations"]["mechanisms"]
        self.assertEqual(entry["mechanism_id"], MECH)
        self.assertEqual(entry["suppressed_count"], 9)
        self.assertEqual(entry["entrypoint_relpath"], WRAPPER_REL)

    def test_the_exit_is_rendered_from_the_state_action_registry(self):
        self._suppress(3)
        self._queue()
        status = self._status()
        (entry,) = status["suppressed_invocations"]["mechanisms"]
        state = status["open_external_write_bypass"]["writer_states"][WRITER_REL]
        self.assertEqual(
            entry["action"],
            state_actions.instruction_for_state(
                state_actions.writer_state_key(state), WRITER_REL))

    def test_a_suppressed_mechanism_with_no_declared_state_gets_the_registrys_route(self):
        """No open queue entry: there is no declared state, so the registry's own
        refusal-to-characterise route is what is rendered. Never a sentence
        composed here."""
        self._suppress(2)
        (entry,) = self._status()["suppressed_invocations"]["mechanisms"]
        self.assertEqual(entry["action"],
                         state_actions.route_for_unclassified_state(WRAPPER_REL))

    def test_removing_the_pause_marker_restores_the_all_clear(self):
        """Leavability. The gate clears exactly when the harm stops -- the same
        act that resumes the wrapper -- and it clears without anything having to
        edit or delete the record of what happened."""
        self._suppress(9)
        self.assertFalse(self._status()["normal_status_allowed"])
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.pause").unlink()
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").unlink()
        status = self._status()
        self.assertTrue(status["normal_status_allowed"], status)
        self.assertFalse(status["suppressed_invocations"]["active"])
        (past,) = status["suppressed_invocations"]["previously_suppressed"]
        self.assertEqual(past["suppressed_count"], 9)

    def test_the_read_path_does_not_mutate_the_event(self):
        """`--overall` self-heals and WRITES. It must not write HERE: it is the
        command most likely to observe suppression, and if observing it erased it
        the act of looking would destroy the evidence of the harm."""
        self._suppress(9)
        path = Path(suppressed_invocation.event_path(str(self.p.root), MECH))
        before_bytes = path.read_bytes()
        before_stat = os.stat(str(path))
        self._status()
        self._status()
        self.assertEqual(before_bytes, path.read_bytes())
        self.assertEqual(before_stat.st_mtime_ns, os.stat(str(path)).st_mtime_ns)

    def test_an_unknown_entanglement_does_not_render_as_absence(self):
        self._suppress(1, carries_read_outputs=None, entangled_read_outputs=[])
        (entry,) = self._status()["suppressed_invocations"]["mechanisms"]
        self.assertEqual(entry["known_entangled_outputs"]["determination"],
                         suppressed_invocation.ENTANGLEMENT_UNKNOWN)
        self.assertTrue(entry["read_outputs_may_be_suppressed"])

    def test_a_verified_separate_companion_is_the_only_case_that_reads_as_safe(self):
        self._suppress(
            1, carries_read_outputs=False,
            separate_readonly_entrypoint="scripts/run_x_digest.sh",
            entangled_read_outputs=[])
        (entry,) = self._status()["suppressed_invocations"]["mechanisms"]
        self.assertFalse(entry["read_outputs_may_be_suppressed"])

    def test_an_unreadable_event_withholds_the_all_clear_with_a_route(self):
        self.p.pause_marker()
        path = Path(suppressed_invocation.event_path(str(self.p.root), MECH))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{truncated", encoding="utf-8")
        status = self._status()
        self.assertFalse(status["normal_status_allowed"], status)
        (bad,) = status["suppressed_invocations"]["unreadable"]
        self.assertEqual(bad["action"],
                         state_actions.route_for_unidentified_record(bad["path"]))

    def test_an_inaccessible_events_directory_is_a_scan_error_not_an_all_clear(self):
        self._suppress(1)
        d = self.p.root / EVENTS_DIR_REL
        os.chmod(str(d), 0o000)
        self.addCleanup(os.chmod, str(d), 0o700)
        status = self._status()
        self.assertIsNotNone(status["suppressed_invocations"]["scan_error"])
        self.assertFalse(status["normal_status_allowed"])

    def test_an_inaccessible_pause_marker_fails_closed_to_active(self):
        self._suppress(1)
        d = self.p.root / PAUSED_DIR_REL
        os.chmod(str(d), 0o000)
        self.addCleanup(os.chmod, str(d), 0o700)
        status = self._status()
        self.assertTrue(status["suppressed_invocations"]["active"], status)
        self.assertFalse(status["normal_status_allowed"])

    def test_the_surface_is_json_serialisable(self):
        self._suppress(2)
        status = self._status()
        self.assertEqual(json.loads(json.dumps(status["suppressed_invocations"])),
                         status["suppressed_invocations"])


# ===========================================================================
# 7. Structural / boundary
# ===========================================================================

class TestStructuralDiscipline(unittest.TestCase):

    def test_the_recorder_is_enrolled_for_emission(self):
        self.assertIn("suppressed_invocation.py",
                      agent_emitter._EXTERNAL_WRITE_LIB_FILES)

    def test_the_path_the_guard_embeds_matches_the_emitters_own_lib_relpath(self):
        """Duplicated-by-value across the build/emitted boundary, pinned equal
        here -- the same anti-drift discipline every other constant crossing
        this boundary carries."""
        self.assertEqual(
            upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
            f"{agent_emitter._EXTERNAL_WRITE_LIB_REL}/suppressed_invocation.py")

    def test_the_recorder_imports_nothing_it_cannot_be_sure_of(self):
        """It runs under the SCHEDULER's environment -- not an activated venv --
        so a bare `python3` may be a different interpreter than the project's.
        Stdlib only, and NOTHING from this package: an import chain that can
        fail is a count silently never recorded."""
        tree = ast.parse(_RECORDER_SOURCE.read_text(encoding="utf-8"))
        allowed = {"argparse", "errno", "fcntl", "json", "os", "stat", "sys",
                   "tempfile", "time", "datetime", "typing", "__future__",
                   "contextlib"}
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                seen.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                seen.add((node.module or "").split(".")[0])
        self.assertFalse(seen - allowed,
                         f"unexpected imports in the recorder: {sorted(seen - allowed)}")
        self.assertNotIn("external_write", seen)

    def test_the_events_directory_has_exactly_one_spelling(self):
        """The recorder owns its own home; every consumer imports it. A
        re-spelled path literal is how two halves of one mechanism come to
        disagree about where the record lives."""
        hits = []
        for path in sorted((_WIZARD / "agents" / "lib" / "external_write").glob("*.py")):
            if path.name == "suppressed_invocation.py":
                continue
            if EVENTS_DIR_REL in path.read_text(encoding="utf-8"):
                hits.append(path.name)
        for path in sorted((_WIZARD / "scripts" / "lib").glob("*.py")):
            if path.name.startswith("test_"):
                continue
            if EVENTS_DIR_REL in path.read_text(encoding="utf-8"):
                hits.append(path.name)
        self.assertEqual(hits, [])

    def test_the_recorder_does_not_respell_the_paused_mechanisms_directory(self):
        """That value is already spelled in five places across the
        toolkit/emitted boundary by a deliberate duplicated-by-value discipline.
        This module adds no sixth: the guard hands it the pause-state path, and
        the health surface passes its own constant."""
        self.assertNotIn(PAUSED_DIR_REL,
                         _RECORDER_SOURCE.read_text(encoding="utf-8"))

    def test_the_module_docstring_states_the_ceiling_and_the_residual(self):
        doc = ast.get_docstring(ast.parse(
            _RECORDER_SOURCE.read_text(encoding="utf-8"))) or ""
        self.assertIn("entrypoint", doc.lower())
        for claim in ("does not", "guard fired"):
            self.assertIn(claim, doc.lower(),
                          "the docstring must state the honest scope and ceiling")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
