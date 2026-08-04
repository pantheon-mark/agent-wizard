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
import collections
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
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

#: The build root the reach pass asks the recorder's id rule through. REQUIRED by
#: the production signature -- there is no value of it that means "skip the check" --
#: so this helper supplies the real one rather than a default existing anywhere.
_BUILD_ROOT = _WIZARD.parent


def upgrade_paused_entrypoint_guards(project_dir, build_root=_BUILD_ROOT):
    """Test-local wrapper over the real pass, defaulting the build root.

    The default lives HERE and not in the production signature on purpose: a
    default there silently skipped the id pre-check, which is a pass-by-default on a
    check whose absence is the defect it exists to prevent.
    ``test_the_production_signature_requires_a_build_root`` pins that.
    """
    return upgrade_reconcile.upgrade_paused_entrypoint_guards(
        project_dir, build_root)

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
#: The id a colliding bespoke stem is re-keyed to by the identity split.
#: DELIBERATELY SHARES NO SUBSTRING WITH ``MECH``. The realistic re-key is
#: relpath-derived (``scripts_finish_estate_cleanup``), which CONTAINS the old
#: id -- so every "the old name is gone" assertion below would have matched the
#: new name's own substring and passed while proving nothing. Caught exactly
#: that way on the first run of these tests.
NEW_ID = "rekeyed_bespoke_writer"


def _pause_record_paths(mechanism_id):
    """Every file the stale-pause route must name, built the way the surface builds
    it -- from the health module's own directory constant and suffix tuple, never a
    re-spelled path."""
    return [os.path.join(PAUSED_DIR_REL, f"{mechanism_id}{suffix}")
            for suffix in capability_health.PAUSE_MARKER_SUFFIXES]
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

    def test_the_block_makes_no_unconditional_continuity_promise(self):
        """The comment written into the operator's OWN file used to promise, for every
        pause, that a genuinely separate read-only entrypoint was unaffected.

        That is the same unconditional claim class the impact notice REFUSES to make
        unless a separate read-only entrypoint was positively verified to survive --
        and this function is not passed that determination, so it cannot establish it
        for any particular pause. It therefore says nothing about it: the honest
        alternative to a promise nothing checked is silence, not a softer promise.
        """
        block = self._block()
        self.assertNotIn("not affected by this guard", block)
        for claim in upgrade_reconcile._WITHDRAWN_CONTINUITY_CLAIMS:
            self.assertNotIn(claim, block)
        # ...and it still says everything it CAN establish.
        self.assertIn("was found to change something outside this project", block)
        self.assertIn("rebuild-paused-capability", block)

    def test_the_withdrawn_promise_key_matches_the_HISTORICAL_body(self):
        """The population that matters is the wrappers already paused. The first
        release wrapped that sentence across two comment lines, so a key spelled from
        today's one-line form would match none of them -- a false negative that reads
        exactly like "no operator was ever told this"."""
        body = _historical_guard_block(
            MECH, WRITER_REL,
            upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH))
        self.assertTrue(
            any(claim in body
                for claim in upgrade_reconcile._WITHDRAWN_CONTINUITY_CLAIMS),
            "the search key misses the wrapping the first release emitted")


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
        upgrade_paused_entrypoint_guards  # API presence
        self.p.pause_marker()
        self.p.pause_state()
        self.p.write(WRITER_REL, "# flagged writer\n")

    def _sweep(self):
        return upgrade_paused_entrypoint_guards(self.p.root)

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
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [MECH], report)
        self.assertIn(upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
                      self._wrapper_text())

    def test_the_operators_own_payload_is_byte_identical_afterwards(self):
        upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(self._outside_the_guard(self.before),
                         self._outside_the_guard(self._wrapper_text()))

    def test_the_marker_check_the_guard_pauses_on_is_byte_identical_afterwards(self):
        """The whole risk of touching an existing guard: a rewrite that changes
        what the `-e` test looks at silently UN-PAUSES a live writer."""
        marker_line = [l for l in self.before.splitlines() if "[ -e " in l]
        upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(
            marker_line,
            [l for l in self._wrapper_text().splitlines() if "[ -e " in l])

    def test_the_upgraded_guard_still_stops_the_payload(self):
        upgrade_paused_entrypoint_guards(self.p.root)
        self.p.install_recorder()
        proc = self.p.run_wrapper()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse((self.p.root / "payload_ran.txt").exists())

    def test_the_historical_guards_own_comment_lines_are_left_alone(self):
        """Deliberately the SMALLEST possible change to a wrapper on the
        fail-closed pause-safety path: one line inserted, nothing rewritten. It
        also means this sweep does not quietly overwrite the historical notice
        wording a separate correction pass owns."""
        upgrade_paused_entrypoint_guards(self.p.root)
        for line in self.before.splitlines():
            if line.startswith("# ") and "safe-paused" in line:
                self.assertIn(line, self._wrapper_text().splitlines())

    def test_nine_real_wrapper_invocations_of_a_historically_paused_wrapper_report_nine(self):
        """The estate's shape, reproduced end to end: a wrapper paused BEFORE
        this tripwire existed, invoked nine times. Nine is asserted from nine
        real ``/bin/sh`` invocations, never from nine direct recorder calls --
        a fixture that called the recorder directly would prove the arithmetic
        and say nothing about reach."""
        upgrade_paused_entrypoint_guards(self.p.root)
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
        upgrade_paused_entrypoint_guards(self.p.root)
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
        upgrade_paused_entrypoint_guards(self.p.root)
        self.p.install_recorder()
        self.assertEqual(self.p.run_wrapper().returncode, 0)
        entangled = self.p.event()["known_entangled_outputs"]
        self.assertEqual(entangled["determination"],
                         suppressed_invocation.ENTANGLEMENT_ENTANGLED)
        self.assertEqual(entangled["labels"], ["digest", "backup"])

    def test_the_sweep_is_idempotent_and_does_not_rewrite_a_current_guard(self):
        upgrade_paused_entrypoint_guards(self.p.root)
        after_first = self._wrapper_text()
        stat_before = os.stat(str(self.p.root / WRAPPER_REL))
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["already_current"], [MECH], report)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(after_first, self._wrapper_text())
        self.assertEqual(stat_before.st_mtime_ns,
                         os.stat(str(self.p.root / WRAPPER_REL)).st_mtime_ns)

    def test_the_wrappers_executable_bit_survives(self):
        upgrade_paused_entrypoint_guards(self.p.root)
        self.assertTrue(os.access(str(self.p.root / WRAPPER_REL), os.X_OK))

    def test_a_guard_naming_a_different_marker_is_refused_untouched(self):
        """A guard whose embedded marker reference this sweep cannot reconstruct
        is one whose pause semantics it does not understand. It is left exactly
        as it is: a missing count is far cheaper than an un-paused writer."""
        text = self._wrapper_text().replace(
            upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH),
            "../.wizard/paused-mechanisms/some_other_id.pause")
        self.p.write(WRAPPER_REL, text, mode=0o755)
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [MECH])
        self.assertEqual(text, self._wrapper_text())

    def test_two_guard_blocks_in_one_wrapper_are_refused_untouched(self):
        text = self._wrapper_text()
        doubled = text + "\n" + text
        self.p.write(WRAPPER_REL, doubled, mode=0o755)
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [MECH])
        self.assertEqual(doubled, self._wrapper_text())

    def test_a_guard_with_no_recognisable_paused_message_line_is_refused(self):
        text = self._wrapper_text().replace(
            upgrade_reconcile._GUARD_PAUSED_ECHO_LINE, '  echo "halted"')
        self.p.write(WRAPPER_REL, text, mode=0o755)
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(text, self._wrapper_text())

    def test_a_wrapper_with_no_guard_at_all_is_skipped_not_gated(self):
        self.p.write(WRAPPER_REL, _PAYLOAD, mode=0o755)
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(_PAYLOAD, self._wrapper_text())

    def test_a_state_whose_declared_id_disagrees_with_its_filename_is_refused(self):
        """Identity is the DECLARED value. A filename is a candidate, and a
        disagreement is reported rather than resolved by picking one."""
        self.p.pause_state(MECH, mechanism_id="something_else")
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertTrue(report["refused"])
        self.assertEqual(self.before, self._wrapper_text())

    def test_a_no_entrypoint_state_with_NO_GUARDED_WRAPPER_is_skipped(self):
        """RETARGETED, not weakened, and the reason is the finding below.

        This asserted that a ``paused_live_write`` record with no
        ``entrypoint_relpath`` is skipped **while a guarded wrapper for that same
        mechanism sat in the fixture** -- encoding the premise that such a record means
        there is no guard to carry a tripwire. On real operator data that premise is
        false, and it cost this pass its entire reach (see the sibling test below).
        What is genuinely true, and what this now asserts, is narrower: with no guarded
        wrapper claiming this mechanism's marker, there is nothing here.
        """
        self.p.write(WRAPPER_REL, _PAYLOAD, mode=0o755)  # guard removed
        self.p.pause_state(MECH, entrypoint_relpath=None,
                           state="paused_live_write")
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(report["refused"], [])
        self.assertEqual(_PAYLOAD, self._wrapper_text())

    def test_a_GUARDED_wrapper_is_reached_though_the_record_names_none(self):
        """★ THE REAL ESTATE'S SHAPE, and the hole this class exists to close.

        Measured on a copy of a real operator project: both pause records are
        ``paused_live_write`` with ``entrypoint_relpath: null``, and
        ``agents/cron/run_estate_upkeep.sh`` carries a live guard, for that same
        mechanism id, with **no recorder lines at all**. Six fix rounds of green
        fixtures could not see it, because every fixture set the field the code keyed
        on. The guard names this mechanism's own pause marker; that is the join.
        """
        self.p.pause_state(MECH, entrypoint_relpath=None,
                           state="paused_live_write")
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [MECH], report)
        self.assertIn(upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
                      self._wrapper_text())
        # The recorder is told the wrapper that was actually invoked, and the marker
        # the guard pauses on is untouched.
        self.assertIn(f"--entrypoint '{WRAPPER_REL}'", self._wrapper_text())
        self.assertEqual([l for l in self.before.splitlines() if "[ -e " in l],
                         [l for l in self._wrapper_text().splitlines()
                          if "[ -e " in l])

    def test_an_absent_marker_directory_is_not_an_error(self):
        """A project that never paused anything is the overwhelmingly common
        case -- including every fresh build. It must report nothing."""
        with tempfile.TemporaryDirectory() as t:
            report = upgrade_paused_entrypoint_guards(Path(t))
            self.assertEqual(report["upgraded"], [])
            self.assertIsNone(report["scan_error"])

    def test_an_inaccessible_marker_directory_is_a_scan_error_not_silence(self):
        d = self.p.root / PAUSED_DIR_REL
        os.chmod(str(d), 0o000)
        self.addCleanup(os.chmod, str(d), 0o700)
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertIsNotNone(report["scan_error"])

    def test_an_unparseable_state_record_is_reported_not_skipped_silently(self):
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
            "{not json", encoding="utf-8")
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertTrue(report["refused"])


class TestNothingInTheReachPassCanAbortTheUpgrade(unittest.TestCase):
    """This pass runs UNCONDITIONALLY on every reconcile, ahead of the impact
    notice and both durable blocking post-conditions. An exception escaping it does
    not un-pause anything -- the write is temp-file + atomic replace -- but it aborts
    everything after it: a raw traceback in front of a non-technical operator, pauses
    already applied, no notice written, and a previously-recorded blocking entry left
    permanently uncleared. An ordinary read-only directory is enough to cause it.

    A tripwire is an observability improvement. It may cost a tripwire; it may never
    cost the upgrade."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.before = self.p.historical_wrapper().read_text(encoding="utf-8")
        self.p.pause_marker()
        self.p.pause_state()

    def test_an_unwritable_wrapper_directory_is_refused_not_raised(self):
        d = self.p.root / "scripts"
        os.chmod(str(d), 0o500)
        self.addCleanup(os.chmod, str(d), 0o700)
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [MECH])
        self.assertIn("could not be written", report["refused"][0]["reason"])

    def test_the_guard_survives_a_refused_write_byte_for_byte(self):
        d = self.p.root / "scripts"
        os.chmod(str(d), 0o500)
        self.addCleanup(os.chmod, str(d), 0o700)
        upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(
            self.before,
            (self.p.root / WRAPPER_REL).read_text(encoding="utf-8"),
            "a failed write must leave the guard exactly as it was")

    def test_a_whole_reconcile_still_completes_and_writes_its_notice(self):
        """The property that actually matters to the operator, asserted end to end
        through ``reconcile_upgrade`` rather than at the helper."""
        self.p.write(WRITER_REL,
                     "from external_write.run_envelope import mint_run_envelope\n")
        d = self.p.root / "scripts"
        os.chmod(str(d), 0o500)
        self.addCleanup(os.chmod, str(d), 0o700)
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _WIZARD.parent, from_version="v0.22.0",
            to_version="v0.23.0")
        self.assertIsNotNone(result.notice_path,
                             "the upgrade must still write its impact notice")
        self.assertTrue(Path(result.notice_path).is_file())

    def test_an_unexpected_failure_per_wrapper_is_contained(self):
        """The backstop, exercised rather than assumed: it exists because of WHERE
        this is called from, not because a particular failure is expected."""
        boom = upgrade_reconcile._insert_tripwire_into_existing_guard

        def explode(*_a, **_k):
            raise RuntimeError("something nobody anticipated")

        upgrade_reconcile._insert_tripwire_into_existing_guard = explode
        self.addCleanup(setattr, upgrade_reconcile,
                        "_insert_tripwire_into_existing_guard", boom)
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [MECH])
        self.assertIn("nobody anticipated", report["refused"][0]["reason"])

    def test_a_restore_that_ITSELF_fails_says_so_rather_than_claiming_success(self):
        """The double-failure path: verification failed AND putting the original back
        failed too. That is the one case where the wrapper is in a state nobody
        verified, so it is also the one case where "the original has been restored"
        must not be printed regardless.

        Tested at the contract, because no ordinary filesystem state produces both
        halves at once -- a mutation that removed the honest branch survived the whole
        behavioural battery, which is what a defensive claim looks like when nothing
        exercises it.
        """
        real = upgrade_reconcile._atomic_write

        def refuse(*_a, **_k):
            raise OSError(28, "No space left on device")

        upgrade_reconcile._atomic_write = refuse
        self.addCleanup(setattr, upgrade_reconcile, "_atomic_write", real)
        restored, reason = upgrade_reconcile._restore_wrapper(
            self.p.root / WRAPPER_REL, self.before, "it did not read back as written")
        self.assertFalse(restored)
        self.assertIn("also failed", reason)
        self.assertIn("needs a person", reason)
        self.assertNotIn("the original has been restored", reason)
        # And the ESCALATION is what the caller derives from it: whichever check
        # failed, a file that could not be put back is the needs-a-person class.
        for checked in (upgrade_reconcile._REFUSED_NOT_VERIFIED,
                        upgrade_reconcile._REFUSED_READBACK_FAILED):
            outcome, _ = upgrade_reconcile._restore_after_failed_check(
                self.p.root / WRAPPER_REL, self.before, checked, "why")
            self.assertEqual(outcome, upgrade_reconcile._REFUSED_NEEDS_PERSON)
            self.assertIn("needs a person",
                          upgrade_reconcile._REFUSAL_OPERATOR_NOTES[outcome])

    def test_a_restore_that_succeeds_says_that_instead(self):
        """The positive control: without it, a function that always reported failure
        would satisfy the assertion above."""
        restored, reason = upgrade_reconcile._restore_wrapper(
            self.p.root / WRAPPER_REL, self.before, "it did not read back as written")
        self.assertTrue(restored)
        self.assertIn("the original has been restored", reason)
        self.assertNotIn("also failed", reason)
        # A successful restore keeps WHICH CHECK FAILED as the outcome -- the two
        # checks are different facts and must not collapse onto one label.
        for checked in (upgrade_reconcile._REFUSED_NOT_VERIFIED,
                        upgrade_reconcile._REFUSED_READBACK_FAILED):
            outcome, _ = upgrade_reconcile._restore_after_failed_check(
                self.p.root / WRAPPER_REL, self.before, checked, "why")
            self.assertEqual(outcome, checked)
        self.assertEqual(
            self.before,
            (self.p.root / WRAPPER_REL).read_text(encoding="utf-8"))

    def test_a_failing_entanglement_label_write_does_not_abort_the_upgrade(self):
        """The same shape one function over, inside the per-mechanism loop."""
        self.p.pause_state()
        d = self.p.root / PAUSED_DIR_REL
        os.chmod(str(d), 0o500)
        self.addCleanup(os.chmod, str(d), 0o700)
        self.assertFalse(upgrade_reconcile._record_pause_entanglement(
            self.p.root, MECH, True, ["digest"]))


class TestTheOperatorsOwnLineEndingsAndFileShape(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.p.pause_marker()
        self.p.pause_state()

    def _crlf_wrapper(self):
        path = self.p.historical_wrapper()
        text = path.read_text(encoding="utf-8")
        path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        os.chmod(str(path), 0o755)
        return path

    def test_a_crlf_wrapper_is_refused_by_name_and_left_byte_for_byte(self):
        """``Path.read_text`` applies universal newlines, so before this was fixed a
        CRLF wrapper read back LF-normalised: the whole-file post-condition compared
        two normalised strings, passed, and the write then converted every line
        ending in the operator's payload. Measured at the time: 10 CRLF pairs in, 0
        out, reported as ``upgraded``, while the docstring claimed byte-identical.

        It refuses rather than adapting because the inserted lines use backslash
        continuations, and a CR before the newline breaks those -- an ending-aware
        insertion would emit a guard that does not parse as intended."""
        path = self._crlf_wrapper()
        before = path.read_bytes()
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [MECH])
        self.assertIn("line endings", report["refused"][0]["reason"])
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(before.count(b"\r\n"), path.read_bytes().count(b"\r\n"))

    def test_an_lf_wrapper_is_still_upgraded_and_keeps_lf(self):
        """The control: without it, the assertion above is satisfied by refusing
        everything."""
        path = self.p.historical_wrapper()
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [MECH])
        self.assertEqual(path.read_bytes().count(b"\r\n"), 0)

    def test_a_symlinked_wrapper_becomes_a_regular_file_ONCE_and_stays_paused(self):
        """Disclosed rather than left to be discovered: the atomic replace breaks
        the link. Measured here so the DISCLOSURE is accurate about frequency -- it
        happens on the pass that installs the tripwire and on no later pass, because
        every later one finds the lines already present and performs no write."""
        real = self.p.write("real/w.sh", "", mode=0o755)
        target = self.p.historical_wrapper()
        real.write_bytes(target.read_bytes())
        os.chmod(str(real), 0o755)
        target.unlink()
        os.symlink("../real/w.sh", str(target))
        self.assertTrue(os.path.islink(str(target)))

        self.assertEqual(
            upgrade_paused_entrypoint_guards(self.p.root)["upgraded"], [MECH])
        self.assertFalse(os.path.islink(str(target)))
        self.assertTrue(os.access(str(target), os.X_OK))
        self.assertIn(upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH),
                      target.read_text(encoding="utf-8"),
                      "it must still be paused on the same marker")

        stat_after_first = os.stat(str(target)).st_mtime_ns
        for _ in range(3):
            report = upgrade_paused_entrypoint_guards(self.p.root)
            self.assertEqual(report["already_current"], [MECH])
            self.assertEqual(report["upgraded"], [])
        self.assertEqual(stat_after_first, os.stat(str(target)).st_mtime_ns,
                         "no later reconcile may write to this wrapper at all")


class TestTheDeclaredIdentityIsWhatCountsAsCurrent(unittest.TestCase):
    """``already_current`` keyed on the recorder's PATH, which is
    mechanism-id-independent -- so a guard whose recorder args named the wrong id was
    short-circuited forever. That is reachable: the identity-split rewrite changes the
    embedded ``.pause`` reference and nothing else, after which the guard pauses on
    the new marker while the recorder still passes the legacy id. The record then
    lands under an id whose marker no longer exists, the surface finds no marker for
    it, and the all-clear comes back WHILE THE GUARD IS FIRING."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.p.historical_wrapper(MECH)
        self.p.pause_marker(MECH)
        self.p.pause_state(MECH)
        self.assertEqual(
            upgrade_paused_entrypoint_guards(self.p.root)["upgraded"], [MECH])
        # The identity split: the guard's marker reference is rewritten, and the
        # marker pair moves with it. Nothing rewrites the recorder's arguments.
        self.assertTrue(upgrade_reconcile._rewrite_wrapper_guard_marker_id(
            self.p.root, WRAPPER_REL, MECH, NEW_ID))
        for suffix in (".pause", ".json"):
            (self.p.root / PAUSED_DIR_REL / f"{MECH}{suffix}").unlink()
        self.p.pause_marker(NEW_ID)
        self.p.pause_state(NEW_ID)

    def _wrapper(self):
        return (self.p.root / WRAPPER_REL).read_text(encoding="utf-8")

    def test_a_stale_declared_id_is_repaired_not_reported_current(self):
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [NEW_ID], report)
        self.assertEqual(report["already_current"], [])

    def test_every_id_derived_name_in_the_guard_agrees_afterwards(self):
        upgrade_paused_entrypoint_guards(self.p.root)
        text = self._wrapper()
        self.assertIn(f"--mechanism-id '{NEW_ID}'", text)
        self.assertIn(f"{NEW_ID}.json", text)
        self.assertIn(f"{NEW_ID}.pause", text)
        self.assertNotIn(f"'{MECH}'", text)
        self.assertNotIn(f"{MECH}.json", text)

    def test_the_marker_the_guard_pauses_on_is_untouched_by_the_repair(self):
        before = [l for l in self._wrapper().splitlines() if "[ -e " in l]
        upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(
            before, [l for l in self._wrapper().splitlines() if "[ -e " in l])

    def test_the_repair_is_idempotent(self):
        upgrade_paused_entrypoint_guards(self.p.root)
        text = self._wrapper()
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["already_current"], [NEW_ID])
        self.assertEqual(text, self._wrapper())

    def test_the_record_lands_under_the_id_whose_marker_actually_exists(self):
        """The end of the chain: without the repair the record went under the legacy
        id, the marker lookup for it found nothing, and the surface returned the
        all-clear over a firing guard."""
        upgrade_paused_entrypoint_guards(self.p.root)
        self.p.install_recorder()
        self.assertEqual(self.p.run_wrapper().returncode, 0)
        self.assertEqual(self.p.event(NEW_ID)["suppressed_count"], 1)
        status = capability_health.overall_status(str(self.p.root))
        self.assertFalse(status["normal_status_allowed"], status)
        self.assertTrue(status["suppressed_invocations"]["active"])
        self.assertEqual(status["suppressed_invocations"]["previously_suppressed"], [])


class TestAnIdThatCouldNeverRecordIsNotReportedUpgraded(unittest.TestCase):
    """``_sh_single_quote`` escapes an id so a wrapper with an awkward name is not
    silently exempted -- and the recorder then refused that very id one layer down,
    on a charset copied from a machine-GENERATED id. A mechanism id is DERIVED from
    the operator's own filename, so a space or an apostrophe is ordinary."""

    def _project_with_id(self, mechanism_id):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = _Project(tmp.name)
        p.historical_wrapper(mechanism_id)
        p.pause_marker(mechanism_id)
        p.pause_state(mechanism_id)
        p.install_recorder()
        return p

    def test_a_space_in_the_id_records_end_to_end(self):
        p = self._project_with_id("Daily Report")
        self.assertEqual(
            upgrade_paused_entrypoint_guards(p.root)["upgraded"],
            ["Daily Report"])
        self.assertEqual(p.run_wrapper().returncode, 0)
        self.assertEqual(p.event("Daily Report")["suppressed_count"], 1)

    def test_an_apostrophe_in_the_id_records_end_to_end(self):
        """The only case ``_sh_single_quote`` exists for. Its own test asserted the
        shell text was escaped and never that the recorder accepted it."""
        p = self._project_with_id("o'brien")
        self.assertEqual(
            upgrade_paused_entrypoint_guards(p.root)["upgraded"],
            ["o'brien"])
        self.assertEqual(p.run_wrapper().returncode, 0)
        self.assertEqual(p.event("o'brien")["suppressed_count"], 1)

    def test_an_id_the_recorder_refuses_is_reported_refused_not_upgraded(self):
        """The residual, closed rather than disclosed: an id that cannot keep a
        record must not be claimed as reached. The refusal reason is the RECORDER's
        own, asked through one implementation of the rule."""
        p = self._project_with_id(".hidden")
        report = upgrade_paused_entrypoint_guards(p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [".hidden"])
        self.assertIn("record could not be kept", report["refused"][0]["reason"])
        self.assertNotIn(
            upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
            (p.root / WRAPPER_REL).read_text(encoding="utf-8"),
            "nothing may be installed for an id that can never record")

    def test_the_id_rule_has_exactly_one_implementation(self):
        """The build-side pass asks the recorder's own rule rather than carrying a
        copy of the charset. A second copy is how "installed" and "can record" came
        apart in the first place."""
        toolkit = (_WIZARD / "scripts" / "lib" / "upgrade_reconcile.py").read_text(
            encoding="utf-8")
        self.assertIn("mechanism_id_refusal", toolkit)
        for shape in ("isalnum", "_ID_EXTRA_CHARS"):
            self.assertNotIn(shape, toolkit,
                             "the toolkit must not re-implement the id rule")

    def test_a_rule_that_cannot_be_ASKED_refuses_rather_than_passing(self):
        """Nothing may pass by default; silence must REFUSE.

        This previously asserted the opposite -- that an unresolvable rule returned
        ``None`` and the pass "behaves exactly as it did before the check existed".
        That is a pass-by-default on the one check standing between "the tripwire is
        installed" and "the tripwire can record", so silence there meant "fine" for
        precisely the property whose absence is the defect. The refusal is a plain
        reason rather than an exception, so an unresolvable module still cannot abort
        the upgrade.
        """
        p = self._project_with_id(MECH)
        real = upgrade_reconcile._external_write_module

        def unavailable(*_a, **_k):
            raise ImportError("the recorder module could not be resolved")

        # Patched rather than pointed at a bogus build root: `_external_write_module`
        # goes through `importlib.import_module`, so once ANY caller in the process
        # has imported the recorder, the module is served from the import cache and
        # the root argument no longer decides anything. A test using a bad root would
        # therefore pass for the wrong reason -- it did, before this was measured.
        upgrade_reconcile._external_write_module = unavailable
        self.addCleanup(setattr, upgrade_reconcile, "_external_write_module", real)

        refusal = upgrade_reconcile._recordable_mechanism_id_refusal(
            _BUILD_ROOT, MECH)
        self.assertIsNotNone(refusal)
        self.assertIn("not assumed", refusal)
        report = upgrade_paused_entrypoint_guards(p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual([r["mechanism_id"] for r in report["refused"]], [MECH])
        self.assertNotIn(
            upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
            (p.root / WRAPPER_REL).read_text(encoding="utf-8"))

    def test_a_rule_answering_something_other_than_a_reason_refuses(self):
        """The third outcome. `mechanism_id_refusal` contracts to a reason or None;
        anything else is a rule this cannot interpret, and interpreting it as "fine"
        is the same default-pass by another route."""
        real = upgrade_reconcile._external_write_module

        class Nonsense:
            @staticmethod
            def mechanism_id_refusal(_id):
                return 0   # falsy, and not None

        upgrade_reconcile._external_write_module = lambda *_a, **_k: Nonsense
        self.addCleanup(setattr, upgrade_reconcile, "_external_write_module", real)
        refusal = upgrade_reconcile._recordable_mechanism_id_refusal(
            _BUILD_ROOT, MECH)
        self.assertIsNotNone(refusal)
        self.assertIn("neither a reason nor a clean result", refusal)

    def test_the_production_signature_requires_a_build_root(self):
        """There must be no value of the argument that means "skip the check" -- so
        there is no default. The permissive default lived in the production signature
        for one round."""
        with self.assertRaises(TypeError):
            upgrade_reconcile.upgrade_paused_entrypoint_guards(self.p_root_for_sig())

    def p_root_for_sig(self):
        return self._project_with_id(MECH).root


class TestTheRefusalsReachTheOperator(unittest.TestCase):
    """A wrapper this pass refuses is one that will not report being skipped. Its
    reason was computed and handed to a caller that threw it away, so nobody could
    learn their tripwire had a hole -- the same invisible-gap class this mechanism
    exists to close, one level up. Worse, the round that added the refusal reasons
    wrote OPERATOR-ADDRESSED sentences into that channel ("needs a person to look at
    it before it is relied on again"), which reads as delivered and was not."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _fresh_project(self):
        """A new temp project for the next class in a multi-class loop, each with its
        OWN registered cleanup. Reassigning `self._tmp` and calling cleanup() by hand
        left the original registered for a second cleanup and leaked every
        replacement -- ResourceWarnings on every run."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = _Project(tmp.name)
        return self.p

    def _crlf_paused_wrapper(self):
        path = self.p.historical_wrapper()
        path.write_bytes(
            path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
        os.chmod(str(path), 0o755)
        self.p.pause_marker()
        self.p.pause_state()

    def _notice(self):
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        self.assertIsNotNone(result.notice_path, "no notice was written at all")
        return Path(result.notice_path).read_text(encoding="utf-8")

    def test_a_refused_wrapper_is_named_in_the_impact_notice(self):
        self._crlf_paused_wrapper()
        notice = self._notice()
        self.assertIn(WRAPPER_REL, notice)
        self.assertIn("line endings", notice)

    #: Every refusal class, with a wrapper builder that reaches it. Used to render
    #: EVERY class and assert the same property of all of them, rather than trusting
    #: whichever one a spot-check happened to pick -- the blanket reassurance survived
    #: three rounds partly because each round's test used a class where it was true.
    def _reach_line_endings(self):
        path = self.p.historical_wrapper()
        path.write_bytes(
            path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
        os.chmod(str(path), 0o755)
        self.p.pause_marker()
        self.p.pause_state()

    def _reach_foreign_marker(self):
        text = self.p.historical_wrapper().read_text(encoding="utf-8").replace(
            upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, MECH),
            upgrade_reconcile._wrapper_guard_marker_ref(WRAPPER_REL, "another_job"))
        self.p.write(WRAPPER_REL, text, mode=0o755)
        self.p.pause_marker()
        self.p.pause_state()

    def _reach_unrecognised_guard(self):
        """The class C1 came through: an INVERTED marker test, so the guard cannot
        fire, with the stopped-run message reworded so the anchor is absent."""
        text = self.p.historical_wrapper().read_text(encoding="utf-8")
        text = text.replace('if [ -e "', 'if [ ! -e "').replace(
            upgrade_reconcile._GUARD_PAUSED_ECHO_LINE, '  echo "on hold for now"')
        self.p.write(WRAPPER_REL, text, mode=0o755)
        self.p.pause_marker()
        self.p.pause_state()

    def _reach_unreadable_pause_record(self):
        self.p.historical_wrapper()
        self.p.pause_marker()
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
            "{truncated", encoding="utf-8")

    def _reach_cannot_record_id(self):
        self.p.historical_wrapper(".hidden")
        self.p.pause_marker(".hidden")
        self.p.pause_state(".hidden")

    def _reach_pass_not_run(self):
        self.p.historical_wrapper()
        self.p.pause_marker()
        self.p.pause_state()
        d = self.p.root / PAUSED_DIR_REL
        os.chmod(str(d), 0o000)
        self.addCleanup(os.chmod, str(d), 0o700)

    def _all_reachers(self):
        return (self._reach_line_endings, self._reach_foreign_marker,
                self._reach_unrecognised_guard, self._reach_unreadable_pause_record,
                self._reach_cannot_record_id, self._reach_pass_not_run)

    #: Any wording that asserts, or implies, something about whether a refused
    #: wrapper is still stopped. Three rounds of these were measured false over a
    #: wrapper whose payload ran; the surface now says nothing on the subject at all.
    _PROTECTION_CLAIMS = (
        "still safely paused", "IS still stopped", "is still stopped",
        "Only the record-keeping is missing", "only the record-keeping is missing",
        "the thing that stops it is in place", "Treat it as running",
        "could NOT confirm this one is stopped",
        "could not establish whether this one is stopped",
    )

    def test_NO_operator_surface_claims_anything_about_protection_in_ANY_class(self):
        """★ The Critical, closed by removing the claim rather than rewording it.

        Substring matching over a shell block cannot establish "this guard will stop
        this writer" -- a marker reference and an exit line are both present in a
        block that is inverted, disabled, positioned below the payload, or
        unparseable by the shell. Three attempts to phrase a true claim on that
        evidence each ended up false over a live writer, so there is no claim now.

        Asserted over EVERY refusal class, notice and CLI, because a spot-check on a
        class where such a sentence happened to be true is how the last three
        survived.
        """
        for reach in self._all_reachers():
            with self.subTest(reach=reach.__name__):
                self._fresh_project()
                reach()
                result = upgrade_reconcile.reconcile_upgrade(
                    self.p.root, _BUILD_ROOT, from_version="v0.22.0",
                    to_version="v0.23.0")
                self.assertTrue(result.tripwire_refusals,
                                f"{reach.__name__} reached no refusal")
                notice = Path(result.notice_path).read_text(encoding="utf-8")
                cli = upgrade_reconcile.render_reconcile_result(result)
                for claim in self._PROTECTION_CLAIMS:
                    self.assertNotIn(claim, notice, f"notice: {claim!r}")
                    self.assertNotIn(claim, cli, f"CLI: {claim!r}")

    def test_the_class_C1_came_through_says_only_what_was_established(self):
        """The generic-shape class over a guard that CANNOT fire. It said "This one IS
        still stopped -- we checked"; the payload ran."""
        self._reach_unrecognised_guard()
        notice = self._notice()
        proc = self.p.run_wrapper()
        self.assertTrue((self.p.root / "payload_ran.txt").exists(),
                        "fixture must actually run the payload")
        self.assertIn("the digest was sent", proc.stdout)
        self.assertIn("not arranged the way we expect", notice)
        self.assertIn("nothing above says whether any of those jobs has actually "
                      "been halted", notice)

    def test_each_cause_gets_its_OWN_sentence_not_one_generic_note(self):
        """Five distinct causes previously reached the operator as one identical
        note, which is what made the marker-absent route's single causal sentence
        wrong for two different situations."""
        by_outcome = {}
        for reach in self._all_reachers():
            self._fresh_project()
            reach()
            result = upgrade_reconcile.reconcile_upgrade(
                self.p.root, _BUILD_ROOT, from_version="v0.22.0",
                to_version="v0.23.0")
            for entry in result.tripwire_refusals:
                by_outcome.setdefault(entry["outcome"], set()).add(
                    entry["operator_note"])
        self.assertGreaterEqual(len(by_outcome), 5, sorted(by_outcome))
        # ONE note per cause, all distinct, and none of them the generic fallback.
        # A count threshold was too loose: losing one cause's own sentence still left
        # enough distinct notes to pass.
        generic = upgrade_reconcile._REFUSAL_OPERATOR_NOTES[upgrade_reconcile._REFUSED]
        notes = []
        for outcome, seen in sorted(by_outcome.items()):
            self.assertEqual(len(seen), 1, f"{outcome} rendered {len(seen)} notes")
            note = next(iter(seen))
            self.assertNotEqual(
                note, generic,
                f"{outcome} fell back to the generic sentence, so its cause is no "
                "longer distinguishable")
            notes.append(note)
        self.assertEqual(len(set(notes)), len(notes),
                         "two causes share one sentence: " + repr(sorted(notes)))

    def test_every_refusal_label_is_reportable_and_has_its_own_sentence(self):
        """The dispatcher's membership test decides whether a refusal is REPORTED AT
        ALL, so a label missing from that tuple is a silently dropped refusal -- the
        invisible-gap class this task exists to close. Nothing bound the vocabulary
        when it went from one literal to three."""
        labels = set(upgrade_reconcile._REFUSAL_OUTCOMES)
        notes = set(upgrade_reconcile._REFUSAL_OPERATOR_NOTES)
        self.assertEqual(sorted(labels - notes), [],
                         "reportable labels with no operator sentence")
        self.assertEqual(sorted(notes - labels), [],
                         "sentences for labels the dispatcher would drop")
        for label in sorted(labels):
            self.assertTrue(
                upgrade_reconcile._REFUSAL_OPERATOR_NOTES[label].strip())

    def test_every_refusal_label_the_module_can_RETURN_is_reportable(self):
        """Derived from the source, not from the tuple: a label a refusal site returns
        that the dispatcher does not recognise is dropped in silence."""
        source = (_WIZARD / "scripts" / "lib" / "upgrade_reconcile.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        returned = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or node.value is None:
                continue
            parts = (node.value.elts if isinstance(node.value, ast.Tuple)
                     else [node.value])
            for part in parts:
                if isinstance(part, ast.Name) and part.id.startswith("_REFUSED"):
                    returned.add(part.id)
        self.assertTrue(returned, "the AST sweep must find something")
        for name in sorted(returned):
            self.assertIn(getattr(upgrade_reconcile, name),
                          upgrade_reconcile._REFUSAL_OUTCOMES,
                          f"{name} is returned by a refusal site but the dispatcher "
                          "would not report it")

    #: A reference that READS a label rather than minting one. Declared per row, not
    #: filtered by a name heuristic, so nothing sits silently outside the enumeration.
    #:
    #: DISCLOSED, because it is author-declared like the fact text: whether a row is
    #: minting or reading is a claim by whoever wrote the row, and a `_NON_MINTING`
    #: row is exempt from the SAME-FACT check -- only that one. It is still checked
    #: for a non-blank fact, a count, a reportable label and a sentence (the sentinel
    #: text satisfies the non-blank part), so a reader row cannot be a blank row. The
    #: machine enforces the multiset of references and the same-fact property over the
    #: rows that declare a fact; it cannot tell you that a row lied about being a
    #: reader.
    _NON_MINTING = "reads a label; does not mint one"

    #: EVERY reference to a refusal label, as ROWS -- ``(function, label, count,
    #: fact)`` -- with the fact that site establishes.
    #:
    #: WHY ROWS WITH A COUNT AND NOT A DICT. The first version was a dict keyed on
    #: ``(function, label)`` compared against a SET, so multiplicity was lost twice
    #: over: two minting sites inside ONE function sharing a label were invisible, and
    #: two literal rows that duplicated a key were silently dead. Both were measured.
    #:
    #: That blindness was not academic. TWO of the four original
    #: ``_REFUSED_AMBIGUOUS_GUARD`` sites were in the SAME function -- so the
    #: mechanism built to close the shared-label class would have caught only half of
    #: the defect it was built for. A dict also cannot express "two sites here", which
    #: is the shape the class needs to be able to see.
    #:
    #: Counts are compared as a MULTISET against the AST sweep, so adding a second
    #: site in a function that already has one fails here.
    #:
    #: WHAT IS MACHINE-CHECKED AND WHAT IS NOT, stated in full because a partial
    #: version of this understated it by a step. The machine checks: the multiset of
    #: references matches the source exactly; no row is a dead duplicate; every label
    #: is reportable and has a sentence; and no label that DECLARES A FACT has two
    #: different ones. Author-declared, and unenforceable by any test here: the fact
    #: TEXT (no test can read a condition and tell you what it established), and
    #: WHETHER A ROW MINTS AT ALL -- a ``_NON_MINTING`` row is skipped by the same-fact
    #: check, so mislabelling a minting site as a reader would hide it from exactly the
    #: property this table exists to enforce. (It is NOT skipped by the
    #: fact-is-stated/reportable check, which an earlier wording claimed: that check
    #: runs over every row, and the ``continue`` that used to exempt reader rows is
    #: gone. The description was stricter about what goes unchecked than the code is.)
    _LABEL_REFERENCES = (
        ("_insert_tripwire_into_existing_guard", "_REFUSED_UNREADABLE_WRAPPER", 1,
         "the wrapper could not be read at all"),
        ("_insert_tripwire_into_existing_guard", "_REFUSED_NOT_TEXT", 1,
         "the wrapper is not decodable text"),
        ("_insert_tripwire_into_existing_guard", "_REFUSED_GUARD_NOT_ONE_BLOCK", 1,
         "there is not exactly one complete begin/end guard pair"),
        ("_insert_tripwire_into_existing_guard",
         "_REFUSED_GUARD_MARKERS_OUT_OF_ORDER", 1,
         "the end marker precedes the begin marker"),
        ("_insert_tripwire_into_existing_guard", "_REFUSED_FOREIGN_MARKER", 1,
         "the guard does not name this mechanism's reconstructed marker"),
        ("_insert_tripwire_into_existing_guard", "_REFUSED_LINE_ENDINGS", 1,
         "the guard's stopped-run message is present with CRLF endings"),
        ("_insert_tripwire_into_existing_guard", "_REFUSED_UNRECOGNISED_GUARD", 1,
         "the stopped-run message is not present exactly once in the block"),
        ("_repair_stale_recorder_identity", "_REFUSED_GUARD_REGION_NOT_DELIMITED", 1,
         "the block's message and exit lines are not each present exactly once"),
        ("_repair_stale_recorder_identity", "_REFUSED_GUARD_EXIT_BEFORE_MESSAGE", 1,
         "the block's exit precedes its stopped-run message"),
        ("_refuse_unconfined_change", "_REFUSED_CHANGE_NOT_CONFINED", 1,
         "the whole-file post-condition rejected the prepared change; "
         "nothing was written"),
        ("_publish_guard_change", "_REFUSED_WRITE_FAILED", 1,
         "the write itself raised; the file is unchanged"),
        ("_publish_guard_change", "_REFUSED_READBACK_FAILED", 1,
         "the read-back raised, so there was nothing to compare"),
        ("_publish_guard_change", "_REFUSED_NOT_VERIFIED", 1,
         "the read-back succeeded and differed from what was written"),
        ("_restore_after_failed_check", "_REFUSED_NEEDS_PERSON", 1,
         "a check failed AND the restore failed, so the file's state is unverified"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_UNREADABLE_PAUSE_RECORD", 1,
         "the pause record could not be read"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_UNPARSEABLE_PAUSE_RECORD", 1,
         "the pause record was read but would not parse"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_PAUSE_RECORD_WRONG_SHAPE", 1,
         "the pause record parsed but is not a mapping"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_ID_ABSENT", 1,
         "the record carries no mechanism_id at all"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_ID_NOT_A_NAME", 1,
         "the record declares an id that is not a usable name"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_WRAPPER_NOT_ESTABLISHED", 1,
         "the record names no wrapper and more than one guarded file claims this "
         "mechanism's marker"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_ID_DISAGREEMENT", 1,
         "the record's declared id disagrees with its filename"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_CANNOT_RECORD_ID", 1,
         "no record file can be kept for this id"),
        ("upgrade_paused_entrypoint_guards", "_REFUSED_UNEXPECTED", 1,
         "an unanticipated failure; nothing about the file's state is established"),
        ("reconcile_upgrade", "_REFUSED_PASS_NOT_RUN", 1,
         "the sweep could not run at all; nothing was examined"),
        # --- references that READ a label, minting nothing ----------------------
        ("_refusal_record", "_REFUSED", 1, _NON_MINTING),
        ("_tripwire_refusal_lines", "_REFUSED", 1, _NON_MINTING),
        ("_tripwire_refusal_lines", "_REFUSED_PASS_NOT_RUN", 1, _NON_MINTING),
        ("render_reconcile_result", "_REFUSED", 1, _NON_MINTING),
        ("render_reconcile_result", "_REFUSED_PASS_NOT_RUN", 1, _NON_MINTING),
    )

    def _derived_label_references(self):
        """Every ``_REFUSED*`` reference inside a FUNCTION BODY, by AST.

        Indirection-agnostic rather than clever: a first attempt matched only a
        returned tuple's first element and ``_refusal_record``'s argument, and missed
        two real minting paths -- a label handed to a helper as an argument, and one
        returned from inside a conditional expression. A sweep that has to recognise
        each indirection keeps missing the next one, so this recognises none of them
        and the table says which references mint.

        NOT TOTAL AS A MATCHER, and the earlier wording claiming that was too strong.
        MODULE-SCOPE references are excluded by construction (``self.fn`` is None
        there), so a label held in a module-level table and returned from a function
        that reads that table would be invisible in both halves -- verified. The
        module has no such path today, which makes this sweep COMPLETE FOR THE CURRENT
        STATE, not complete for any state. A future table-driven refusal needs its own
        row here by hand.
        """
        source = (_WIZARD / "scripts" / "lib" / "upgrade_reconcile.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        found = collections.Counter()

        class Walk(ast.NodeVisitor):
            def __init__(self):
                self.fn = None

            def visit_FunctionDef(self, node):
                prev, self.fn = self.fn, node.name
                self.generic_visit(node)
                self.fn = prev

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Name(self, node):
                if (self.fn and isinstance(node.ctx, ast.Load)
                        and node.id.startswith("_REFUSED")):
                    # A COUNTER, not a set. A set lost multiplicity, so two minting
                    # sites inside one function sharing a label were invisible -- and
                    # two of the four sites the shared-label class was built for were
                    # in the same function, so it would have caught half of it.
                    found[(self.fn, node.id)] += 1
                self.generic_visit(node)

        Walk().visit(tree)
        return found

    def _declared_counter(self):
        counter = collections.Counter()
        for function, label, count, _fact in self._LABEL_REFERENCES:
            counter[(function, label)] += count
        return counter

    def test_every_label_reference_is_declared_WITH_ITS_MULTIPLICITY(self):
        derived = self._derived_label_references()
        self.assertTrue(derived, "the AST sweep must find something")
        declared = self._declared_counter()
        self.assertEqual(
            dict(derived - declared), {},
            "a refusal label is referenced more times than this table declares -- if "
            "that is a new minting site, add a row stating what it establishes and "
            "check the label's sentence is true there")
        self.assertEqual(
            dict(declared - derived), {},
            "this table declares references that no longer exist")

    def test_no_row_is_a_dead_duplicate(self):
        """Two literal rows duplicating a key were silently dead in the dict form --
        the later one won and the earlier one described nothing. As rows they would
        instead inflate a count, so this asserts each (function, label) appears once
        with its own count rather than twice."""
        keys = [(f, l) for f, l, _c, _fact in self._LABEL_REFERENCES]
        dupes = sorted(k for k, n in collections.Counter(keys).items() if n > 1)
        self.assertEqual(dupes, [],
                         "duplicated rows -- merge them into one row with a count: "
                         + repr(dupes))

    def _labels_with_conflicting_facts(self, rows):
        """The property, as a function over ROWS so it can be exercised on a fixture.

        Extracted precisely because the real table can no longer make it fail: every
        label is minted at one site today, so run against production this predicate is
        unexercised. A test that cannot fail is the shape this task has removed twice.
        """
        by_label = {}
        for _function, label, _count, fact in rows:
            if fact == self._NON_MINTING:
                continue
            by_label.setdefault(label, set()).add(fact)
        return {label: sorted(facts) for label, facts in by_label.items()
                if len(facts) > 1}

    def test_the_same_fact_property_DETECTS_a_conflict_when_there_is_one(self):
        """★ F9: the property observed RED, on a fixture.

        Against production this predicate returns empty because no label is minted
        twice -- which is the goal, and also means production alone can never
        demonstrate the check works. So it is exercised here on the exact shape it
        exists to catch, INCLUDING the configuration that made the old gate blind:
        two sites in the SAME function.
        """
        conflict_across_functions = (
            ("fn_a", "_REFUSED_X", 1, "fact one"),
            ("fn_b", "_REFUSED_X", 1, "a different fact"),
        )
        self.assertEqual(
            self._labels_with_conflicting_facts(conflict_across_functions),
            {"_REFUSED_X": ["a different fact", "fact one"]})

        conflict_within_one_function = (
            ("fn_a", "_REFUSED_X", 1, "fact one"),
            ("fn_a", "_REFUSED_X", 1, "a different fact"),
        )
        self.assertTrue(
            self._labels_with_conflicting_facts(conflict_within_one_function),
            "two sites in ONE function with different facts is the configuration the "
            "previous gate could not see at all")

        agreeing = (("fn_a", "_REFUSED_X", 2, "one fact"),
                    ("fn_b", "_REFUSED_X", 1, "one fact"))
        self.assertEqual(self._labels_with_conflicting_facts(agreeing), {})
        self.assertEqual(
            self._labels_with_conflicting_facts(
                (("fn_a", "_REFUSED_X", 1, self._NON_MINTING),
                 ("fn_b", "_REFUSED_X", 1, "a fact"))),
            {}, "a reader row must not count as a conflicting fact")

    def test_no_label_in_the_REAL_table_has_conflicting_facts(self):
        self.assertEqual(
            self._labels_with_conflicting_facts(self._LABEL_REFERENCES), {},
            "these labels are minted at sites establishing DIFFERENT facts, so one "
            "sentence cannot be true at all of them -- split the label")

    def test_every_declared_fact_is_stated_and_every_label_is_reportable(self):
        """The table cannot be padded with blanks, and every label in it has to be one
        the dispatcher reports and the notes map answers for."""
        for function, label, count, fact in self._LABEL_REFERENCES:
            self.assertTrue(fact.strip(), f"{function}/{label} declares no fact")
            self.assertGreaterEqual(count, 1, f"{function}/{label} declares no count")
            value = getattr(upgrade_reconcile, label)
            self.assertIn(value, upgrade_reconcile._REFUSAL_OUTCOMES, label)
            self.assertIn(value, upgrade_reconcile._REFUSAL_OPERATOR_NOTES, label)

    def test_the_not_one_block_sentence_is_true_on_a_MISSING_end_marker(self):
        """The sentence's content, not just its label. The route fires on "not exactly
        one complete pair", which includes a wrapper with a begin and NO end -- fewer
        than one block, not more. The old sentence said "more than one"."""
        text = self.p.historical_wrapper().read_text(encoding="utf-8").replace(
            upgrade_reconcile._GUARD_END, "# (end marker removed)")
        self.p.write(WRAPPER_REL, text, mode=0o755)
        self.p.pause_marker()
        self.p.pause_state()
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        (entry,) = result.tripwire_refusals
        self.assertEqual(entry["outcome"],
                         upgrade_reconcile._REFUSED_GUARD_NOT_ONE_BLOCK)
        notice = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertNotIn("has more than one of our safety blocks", notice,
                         "this wrapper has FEWER than one complete block")
        self.assertIn("does not contain exactly one complete safety block", notice)

    def test_a_malformed_pause_record_is_not_called_UNREADABLE(self):
        """F4's sibling: the file read perfectly and would not parse. Read and
        understood are different facts and only the second one failed."""
        self.p.historical_wrapper()
        self.p.pause_marker()
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
            "{not json at all", encoding="utf-8")
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        (entry,) = result.tripwire_refusals
        self.assertEqual(entry["outcome"],
                         upgrade_reconcile._REFUSED_UNPARSEABLE_PAUSE_RECORD)
        notice = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertIn("was read but its contents could not be made sense of", notice)
        self.assertNotIn("could not be read, so we could not tell", notice)

    def test_an_ABSENT_mechanism_id_is_not_called_a_DIFFERENT_one(self):
        """F5. Absent and different are not the same fact, and the remedy differs."""
        self.p.historical_wrapper()
        self.p.pause_marker()
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
            json.dumps({"writer_relpath": WRITER_REL,
                        "entrypoint_relpath": WRAPPER_REL}) + "\n",
            encoding="utf-8")
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        (entry,) = result.tripwire_refusals
        self.assertEqual(entry["outcome"], upgrade_reconcile._REFUSED_ID_ABSENT)
        notice = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertIn("does not say which job it belongs to", notice)
        self.assertNotIn("names a different job", notice)

    def test_a_BLANK_mechanism_id_is_not_called_a_DIFFERENT_one(self):
        """The other half of the absent-vs-different split, and it was still wrong:
        the branch keys on ``is None``, so a record declaring ``""`` was reported as
        naming a DIFFERENT job than its filename. Absent, unusable and different are
        three facts; only the third is a disagreement, and only it is repaired by
        choosing between two names."""
        self.p.historical_wrapper()
        self.p.pause_marker()
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
            json.dumps({"mechanism_id": "   ",
                        "writer_relpath": WRITER_REL,
                        "entrypoint_relpath": WRAPPER_REL}) + "\n",
            encoding="utf-8")
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        (entry,) = result.tripwire_refusals
        notice = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertNotIn("names a different job", notice)
        self.assertEqual(entry["outcome"], upgrade_reconcile._REFUSED_ID_NOT_A_NAME)
        self.assertIn("does not name a job", notice)

    def test_a_NON_STRING_mechanism_id_is_not_called_a_DIFFERENT_one(self):
        """Same branch, every other shape a JSON record can legally hold. Each was
        measured rendering "names a different job than its own filename does"."""
        for value in (0, False, [], {}, 123):
            with self.subTest(value=value):
                p = self._fresh_project()
                p.historical_wrapper()
                p.pause_marker()
                (p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
                    json.dumps({"mechanism_id": value,
                                "writer_relpath": WRITER_REL,
                                "entrypoint_relpath": WRAPPER_REL}) + "\n",
                    encoding="utf-8")
                result = upgrade_reconcile.reconcile_upgrade(
                    p.root, _BUILD_ROOT, from_version="v0.22.0",
                    to_version="v0.23.0")
                (entry,) = result.tripwire_refusals
                self.assertNotIn(
                    "names a different job",
                    Path(result.notice_path).read_text(encoding="utf-8"))
                self.assertEqual(entry["outcome"],
                                 upgrade_reconcile._REFUSED_ID_NOT_A_NAME)

    def test_the_region_DIAGNOSTIC_agrees_with_its_declared_fact(self):
        """The operator sentence at this site was corrected to "record-keeping lines
        that are not the ones we would write"; the diagnostic on the same event still
        said the lines were "for a different mechanism". The route fires whenever the
        block's lines are not the ones we would write now -- which includes
        reformatted lines for THIS job -- so whose they are is not established.

        AST at the site rather than a text window: prose discussing the old wording in
        order to explain it is not the wording (the same reason the sibling
        diagnostic test above is AST-based).
        """
        source = (_WIZARD / "scripts" / "lib" / "upgrade_reconcile.py").read_text(
            encoding="utf-8")
        reasons = []
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Return)
                    and isinstance(node.value, ast.Tuple)
                    and node.value.elts):
                continue
            first = node.value.elts[0]
            if not (isinstance(first, ast.Name)
                    and first.id == "_REFUSED_GUARD_REGION_NOT_DELIMITED"):
                continue
            reasons.append("".join(
                part.value for part in ast.walk(node.value)
                if isinstance(part, ast.Constant) and isinstance(part.value, str)))
        self.assertEqual(len(reasons), 1, reasons)
        self.assertNotIn("for a different mechanism", reasons[0])
        self.assertIn("not the ones we would write", reasons[0])

    def test_the_correction_reaches_a_wrapper_this_pass_just_upgraded(self):
        """The realistic sequence: a wrapper paused by the release that emitted the
        promise, whose guard this pass gives its record-keeping lines.

        ASSERTS THE BYTES, not only the sentence. The first version of this test built
        exactly this scenario and checked only that the sentence survived -- so the
        notice's "Nothing here changes them", about a file the same run had just
        rewritten, shipped green through the test named for the case that falsifies it.
        """
        wrapper = self.p.historical_wrapper()
        before = wrapper.read_bytes()
        self.p.pause_marker()
        self.p.pause_state()
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        self.assertEqual(result.tripwire_refusals, [])
        after = wrapper.read_bytes()
        self.assertNotEqual(before, after,
                            "this run was expected to add the record-keeping lines")
        self.assertIn(
            b"separate read-only entrypoint is not affected by this guard", after,
            "the guard comment was expected to survive the insertion")
        self.assertIsNotNone(result.notice_path,
                            "nothing told this operator the sentence in their own "
                            "file was never checked")
        notice = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertIn(WRAPPER_REL, notice)
        self.assertIn("nothing had checked whether that was true", notice)
        # The file it names CHANGED on this run, so the notice may not say otherwise.
        self.assertNotIn("Nothing here changes them", notice)
        self.assertNotIn("left exactly as they are", notice)

    def test_a_guarded_wrapper_naming_ANOTHER_mechanisms_marker_is_not_claimed(self):
        """Deny-by-default on the join. The wrapper's path decides nothing; the marker
        the guard itself tests is the only thing that says which mechanism it gates."""
        self.p.historical_wrapper(mechanism_id="some_other_job")
        self.p.pause_marker()
        self.p.pause_state(entrypoint_relpath=None, state="paused_live_write")
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        self.assertEqual(report["refused"], [])
        self.assertNotIn(
            upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
            (self.p.root / WRAPPER_REL).read_text(encoding="utf-8"))

    def test_TWO_guarded_wrappers_claiming_one_marker_is_refused_not_guessed(self):
        """Which one gates the mechanism is not established, so neither is written to
        and the operator is told there is a reporting gap."""
        self.p.historical_wrapper()
        twin = self.p.root / "scripts" / "run_finish_estate_cleanup_copy.sh"
        twin.write_text((self.p.root / WRAPPER_REL).read_text(encoding="utf-8"),
                        encoding="utf-8")
        self.p.pause_marker()
        self.p.pause_state(entrypoint_relpath=None, state="paused_live_write")
        report = upgrade_paused_entrypoint_guards(self.p.root)
        self.assertEqual(report["upgraded"], [])
        (entry,) = report["refused"]
        self.assertEqual(entry["outcome"],
                         upgrade_reconcile._REFUSED_WRAPPER_NOT_ESTABLISHED)
        for path in (WRAPPER_REL, "scripts/run_finish_estate_cleanup_copy.sh"):
            self.assertNotIn(
                upgrade_reconcile.SUPPRESSED_INVOCATION_RECORDER_REL,
                (self.p.root / path).read_text(encoding="utf-8"))

    def test_the_reachable_label_COUNT_in_the_docstring_is_pinned(self):
        """The returns docstring states 14-of-24 and four minting sources. That
        arithmetic has already gone stale twice in this same sentence ("two" when it
        was four; "ANY member" when it was 14 of 24), and the multiplicity table
        reddens on a new label SITE without anyone rereading the number."""
        source = (_WIZARD / "scripts" / "lib" / "upgrade_reconcile.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        mints = collections.defaultdict(set)
        calls = collections.defaultdict(set)

        class Walk(ast.NodeVisitor):
            def __init__(self):
                self.fn = None

            def visit_FunctionDef(self, node):
                prev, self.fn = self.fn, node.name
                self.generic_visit(node)
                self.fn = prev

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_Name(self, node):
                if (self.fn and isinstance(node.ctx, ast.Load)
                        and node.id.startswith("_REFUSED")
                        and node.id != "_REFUSED_OUTCOMES"):
                    mints[self.fn].add(node.id)
                self.generic_visit(node)

            def visit_Call(self, node):
                if self.fn and isinstance(node.func, ast.Name):
                    calls[self.fn].add(node.func.id)
                self.generic_visit(node)

        Walk().visit(tree)
        seed = "_insert_tripwire_into_existing_guard"
        seen, stack = set(), [seed]
        while stack:
            fn = stack.pop()
            if fn in seen:
                continue
            seen.add(fn)
            stack.extend(c for c in calls.get(fn, ()) if c in mints or c in calls)
        reachable = set().union(*(mints.get(fn, set()) for fn in seen)) if seen else set()
        sources = sorted(fn for fn in seen if mints.get(fn))
        self.assertEqual(len(reachable), 14, sorted(reachable))
        self.assertEqual(len(upgrade_reconcile._REFUSAL_OUTCOMES), 25)
        self.assertEqual(sources, ["_insert_tripwire_into_existing_guard",
                                   "_publish_guard_change",
                                   "_refuse_unconfined_change",
                                   "_repair_stale_recorder_identity",
                                   "_restore_after_failed_check"])
        self.assertEqual(len(mints["_publish_guard_change"]
                              | mints["_restore_after_failed_check"]), 4)

    def test_a_DIFFERENT_mechanism_id_still_reads_as_a_disagreement(self):
        """The control for the split above: the route that genuinely IS a
        disagreement must keep saying so."""
        self.p.historical_wrapper()
        self.p.pause_marker()
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.json").write_text(
            json.dumps({"mechanism_id": "some_other_job",
                        "writer_relpath": WRITER_REL,
                        "entrypoint_relpath": WRAPPER_REL}) + "\n",
            encoding="utf-8")
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        (entry,) = result.tripwire_refusals
        self.assertEqual(entry["outcome"],
                         upgrade_reconcile._REFUSED_ID_DISAGREEMENT)
        self.assertIn("names a different job",
                      Path(result.notice_path).read_text(encoding="utf-8"))

    def test_the_region_sentence_does_not_claim_the_lines_belong_to_another_job(self):
        """F3: this route fires whenever the block's record-keeping lines are not the
        ones we would write now, which includes reformatted lines for THIS job. What
        is established is that they do not match, not whose they are."""
        note = upgrade_reconcile._REFUSAL_OPERATOR_NOTES[
            upgrade_reconcile._REFUSED_GUARD_REGION_NOT_DELIMITED]
        self.assertNotIn("for a different job", note)
        self.assertIn("not the ones we would write", note)

    def test_the_unexpected_DIAGNOSTIC_agrees_with_its_declared_fact(self):
        """F6: the operator sentence refuses to state the file's state, and the
        diagnostic on the same event used to assert it. One event, two channels, and
        the table now declares the opposite of what the diagnostic said."""
        # AST, not a text window. The first attempt scanned forward from a phrase and
        # matched the COMMENT that quotes the old wording in order to explain it --
        # the same reason the monopoly gate is AST-based rather than textual: prose
        # discussing a banned sentence is not the sentence.
        source = (_WIZARD / "scripts" / "lib" / "upgrade_reconcile.py").read_text(
            encoding="utf-8")
        reasons = []
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "_refusal_record"):
                continue
            labels = [a.id for a in node.args
                      if isinstance(a, ast.Name) and a.id.startswith("_REFUSED")]
            if "_REFUSED_UNEXPECTED" not in labels:
                continue
            reasons.append("".join(
                part.value for arg in node.args for part in ast.walk(arg)
                if isinstance(part, ast.Constant) and isinstance(part.value, str)))
        self.assertEqual(len(reasons), 1, reasons)
        for claim in ("keeps the guard it had", "not report being stopped"):
            self.assertNotIn(claim, reasons[0],
                             "the diagnostic asserts a file state its own declared "
                             f"fact says is not established: {claim!r}")
        self.assertIn("not established here", reasons[0])

    def test_the_byte_for_byte_claim_names_its_ONE_exception(self):
        """F8: "every refusal leaves the wrapper byte-for-byte as it was" is a
        universally-quantified claim with a known exception -- the needs-a-person
        branch is exactly the case where a write happened and the restore failed."""
        doc = upgrade_reconcile._insert_tripwire_into_existing_guard.__doc__ or ""
        self.assertIn("byte-for-byte", doc)
        self.assertIn("WITH ONE EXCEPTION", doc)
        self.assertIn("_REFUSED_NEEDS_PERSON", doc)

    def test_the_unexpected_sentence_never_states_the_files_state(self):
        """An unknown failure is one where nobody knows where it stopped, so the
        sentence may not say what happened to the file. The old one said "so the file
        was left as it was"."""
        note = upgrade_reconcile._REFUSAL_OPERATOR_NOTES[
            upgrade_reconcile._REFUSED_UNEXPECTED]
        for claim in ("left as it was", "was left", "unchanged",
                      "keeps the guard it had"):
            self.assertNotIn(claim, note, f"an unknown failure claims {claim!r}")
        self.assertIn("cannot tell from here what state that left it in", note)

    def test_the_section_terminates_the_list_that_precedes_it(self):
        """A markdown list runs on until a blank line, so without one the section's
        headline renders INSIDE the preceding bullet. Gating the pending-work bullet
        removed the blank that had been doing that by accident."""
        text = upgrade_reconcile.render_impact_notice(
            [], "v0.22.0", "v0.23.0",
            tripwire_refusals=[upgrade_reconcile._refusal_record(
                MECH, WRAPPER_REL, upgrade_reconcile._REFUSED_LINE_ENDINGS, "d")])
        lines = text.splitlines()
        idx = next(i for i, l in enumerate(lines)
                   if l.startswith("**One more thing"))
        self.assertEqual(
            lines[idx - 1], "",
            "the section headline is inside the preceding bullet's paragraph: "
            f"preceded by {lines[idx - 1]!r}")

    def test_the_label_reference_sweep_is_not_vacuous(self):
        """The enumeration is only load-bearing if the derivation finds things. A sweep
        that returned nothing would make the comparison pass by emptiness -- the same
        vacuous shape as a zero-test selection."""
        derived = self._derived_label_references()
        self.assertGreaterEqual(len(derived), 20, sorted(derived))
        functions = {fn for fn, _ in derived}
        for expected in ("_insert_tripwire_into_existing_guard",
                         "_publish_guard_change", "upgrade_paused_entrypoint_guards",
                         "reconcile_upgrade"):
            self.assertIn(expected, functions)

    def test_the_notice_routes_to_the_thing_that_CAN_answer_it(self):
        self._reach_line_endings()
        notice = self._notice()
        self.assertIn("tell your assistant", notice.lower())
        self.assertIn("reading the file is what can answer it", notice)
        self.assertIn("nothing above says whether any of those jobs has "
                      "actually been halted", notice)

    def test_a_pass_wide_failure_is_ONE_entry_naming_no_job_end_to_end(self):
        """The real pass-wide route, driven through ``reconcile_upgrade``.

        RETARGETED: this used to ban the literals ``"a paused scheduled job:"`` and
        ``"this one"``, both of which this task's own diff had already deleted -- so
        it could no longer fail, whatever the code did. That is the vacuous-green
        shape one level up from the thing it was watching. It now asserts what the
        behaviour IS: exactly one entry for the whole pass, carrying no subject, with
        its sentence on both surfaces.
        """
        self._reach_pass_not_run()
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        (entry,) = result.tripwire_refusals
        self.assertEqual(entry["outcome"], upgrade_reconcile._REFUSED_PASS_NOT_RUN)
        self.assertEqual(entry["mechanism_id"], "")
        self.assertIsNone(entry["entrypoint_relpath"])
        notice = Path(result.notice_path).read_text(encoding="utf-8")
        cli = upgrade_reconcile.render_reconcile_result(result)
        for surface_name, surface in (("notice", notice), ("CLI", cli)):
            self.assertIn("could not look at your paused scheduled jobs at all",
                          surface, surface_name)

    def test_a_pass_wide_failure_named_after_a_job_STILL_is_not_one_job(self):
        """Pins the outcome half of the pass-wide branch.

        Today the pass-wide record's subject is empty, so the `not subject` half
        catches it on its own and the `outcome ==` half is redundant -- a mutation
        removing it stayed green. That is a second guard covering the case, not a weak
        test; the leg is what would keep a pass-wide record that DID carry a mechanism
        id from rendering as a single job with a reporting gap. Pinned by giving it
        one, so the leg is load-bearing rather than decorative.
        """
        entry = upgrade_reconcile._refusal_record(
            "estate_upkeep", "agents/cron/run_estate_upkeep.sh",
            upgrade_reconcile._REFUSED_PASS_NOT_RUN, "diagnostic")
        # Asserted on the EXACT rendered prefix each surface would emit. An earlier
        # version checked for "estate_upkeep:", which is not a substring of
        # "run_estate_upkeep.sh: ...", so the CLI half of this passed while the CLI
        # was in fact naming the job -- the same substring-overlap trap as a fixture
        # whose two ids share a prefix.
        subject_prefixes = (f"{entry['entrypoint_relpath']}:",
                            f"{entry['mechanism_id']}:")
        rendered = "\n".join(upgrade_reconcile._tripwire_refusal_lines([entry]))
        result = upgrade_reconcile.ReconcileResult(
            operator_project_path=str(self.p.root), from_version="a", to_version="b",
            tripwire_refusals=[entry])
        cli = upgrade_reconcile.render_reconcile_result(result)
        for surface_name, surface in (("notice", rendered), ("CLI", cli)):
            self.assertIn("could not look at your paused scheduled jobs at all",
                          surface, surface_name)
            for prefix in subject_prefixes:
                self.assertNotIn(prefix, surface,
                                 f"{surface_name} names a single job for a pass-wide "
                                 f"failure: {prefix!r}")

    def test_the_notice_says_WHEN_it_was_worked_out(self):
        """The reconcile entry point overwrites one fixed file, so without this a
        reader cannot tell a fresh statement from one left days ago."""
        self._reach_line_endings()
        notice = self._notice()
        self.assertIn("Worked out at ", notice)
        self.assertRegex(notice, r"Worked out at \d{4}-\d{2}-\d{2}T")

    def test_a_refusal_only_notice_does_not_name_a_file_that_does_not_exist(self):
        """The unconditional pending-work-list bullet, two lines from the branch this
        round audited: on a refusal-only notice that file is not written."""
        self._reach_line_endings()
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        notice = Path(result.notice_path).read_text(encoding="utf-8")
        self.assertIsNone(result.migration_queue_path)
        self.assertFalse((self.p.root / upgrade_reconcile.MIGRATION_QUEUE_REL).exists())
        self.assertNotIn("pending-work list", notice)

    def test_the_CLI_carries_the_SAME_sentence_as_the_notice(self):
        """The CLI dropped `operator_note` and kept a reassurance, so the terminal's
        only substantive sentence was the one thing that was not established, and the
        classes that exist BECAUSE they have something specific to say were
        indistinguishable there."""
        self._reach_line_endings()
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        cli = upgrade_reconcile.render_reconcile_result(result)
        notice = Path(result.notice_path).read_text(encoding="utf-8")
        (entry,) = result.tripwire_refusals
        self.assertIn(entry["operator_note"], cli)
        self.assertIn(entry["operator_note"], notice)

    def test_the_needs_a_person_class_is_distinguishable_on_the_CLI(self):
        """It exists because it has something specific to say, and on the terminal
        that has to survive."""
        note = upgrade_reconcile._REFUSAL_OPERATOR_NOTES[
            upgrade_reconcile._REFUSED_NEEDS_PERSON]
        self.assertIn("needs a person", note)
        self.assertNotIn("record-keeping is missing", note)
        result = upgrade_reconcile.ReconcileResult(
            operator_project_path=str(self.p.root), from_version="a", to_version="b",
            tripwire_refusals=[upgrade_reconcile._refusal_record(
                MECH, WRAPPER_REL, upgrade_reconcile._REFUSED_NEEDS_PERSON, "x")])
        self.assertIn("needs a person",
                      upgrade_reconcile.render_reconcile_result(result))

    def test_the_CLI_summary_names_the_refusal_and_points_at_the_notice(self):
        """★ New-1. The notice was written and `render_reconcile_result` returned ""
        in the refusal-only case, so the CLI printed nothing and the record on disk
        was named by no surface -- the invisible-durable-record defect this task
        exists to close, inside the fix for it."""
        self._crlf_paused_wrapper()
        result = upgrade_reconcile.reconcile_upgrade(
            self.p.root, _BUILD_ROOT, from_version="v0.22.0", to_version="v0.23.0")
        out = upgrade_reconcile.render_reconcile_result(result)
        self.assertTrue(out.strip(), "the CLI summary was empty")
        self.assertIn(WRAPPER_REL, out)
        self.assertIn("Windows-style line endings", out)
        self.assertIn(str(result.notice_path), out,
                      "nothing pointed the operator at the notice")

    def test_a_refusal_only_notice_makes_no_claim_about_an_undo_step(self):
        """The `if not mechanisms:` branch describes an outstanding undo-step answer
        for an adapter this pass rewrote. A refusal-only notice reaches it with no
        adapter edited, no undo step and no capability awaiting approval, so every
        clause of it would be about something that did not happen."""
        self._crlf_paused_wrapper()
        notice = self._notice()
        self.assertNotIn("undo step", notice)
        self.assertNotIn("tried out and approved again", notice)
        self.assertIn("Nothing in your project was paused by this upgrade", notice)

    def test_the_renderer_emits_nothing_for_an_empty_refusal_set(self):
        self.assertEqual(upgrade_reconcile._tripwire_refusal_lines([]), [])
        self.assertEqual(upgrade_reconcile._tripwire_refusal_lines(
            [{"mechanism_id": "x", "reason": ""}]), [])


class TestTheStalePauseRouteNamesRealFiles(unittest.TestCase):
    """The route named a STEM (`.wizard/paused-mechanisms/<id>`), which does not
    exist on disk, and said "that record" for a two-file pair whose wrong branch left
    the block in place under a now-false sentence."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = _Project(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.p.pause_marker()
        self.p.pause_state()
        suppressed_invocation.record_suppressed_invocation(
            project_root=str(self.p.root), mechanism_id=MECH,
            entrypoint_relpath=WRAPPER_REL)

    def _entry(self):
        status = capability_health.overall_status(str(self.p.root))
        return status, status["suppressed_invocations"]

    def test_every_path_the_route_names_exists_on_disk(self):
        _status, sup = self._entry()
        (entry,) = sup["mechanisms"]
        named = re.findall(r"`([^`]*paused-mechanisms[^`]*)`", entry["action"])
        self.assertTrue(named, entry["action"])
        for relpath in named:
            self.assertTrue((self.p.root / relpath).exists(),
                            f"the route names {relpath!r}, which does not exist")

    def test_it_names_the_whole_pair_not_the_stem(self):
        _status, sup = self._entry()
        (entry,) = sup["mechanisms"]
        for suffix in capability_health.PAUSE_MARKER_SUFFIXES:
            self.assertIn(f"{MECH}{suffix}", entry["action"])
        self.assertNotIn(f"`{PAUSED_DIR_REL}/{MECH}`", entry["action"])

    def test_removing_the_half_the_guard_READS_stops_the_false_claim(self):
        """Measured before the fix: deleting only `.pause` resumed the wrapper while
        the surface kept saying it was "still switched off and will not run", kept
        withholding the all-clear, and offered no further instruction. The operator
        reached that by doing exactly what the sentence said."""
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.pause").unlink()
        status, sup = self._entry()
        self.assertFalse(sup["active"])
        self.assertTrue(status["normal_status_allowed"], status)
        self.assertEqual(sup["mechanisms"], [])
        self.assertEqual(len(sup["previously_suppressed"]), 1)

    def test_removing_the_whole_pair_also_clears_it(self):
        """The instruction says delete them all, so that has to work too."""
        for suffix in capability_health.PAUSE_MARKER_SUFFIXES:
            (self.p.root / PAUSED_DIR_REL / f"{MECH}{suffix}").unlink()
        status, sup = self._entry()
        self.assertFalse(sup["active"])
        self.assertTrue(status["normal_status_allowed"], status)

    def test_the_any_shape_rule_follows_the_CONSTANT_not_a_re_spelled_literal(self):
        """The branch discriminator was `if suffix == ".pause"`, eight lines under a
        comment claiming one spelling. Load-bearing rather than tidy: the guard-read
        half applies an ANY-SHAPE rule (matching the wrapper's own `[ -e ]`, which
        pauses on a directory too), and the other half applies a regular-file rule.
        A re-spelled literal would silently route the whole guard-read family into
        the wrong rule the moment the constant changed.

        Asserted through the constant, and with a NON-regular path, because that is
        the only case where the two rules differ observably.
        """
        for name in (f"{MECH}.pause", f"{MECH}.json"):
            path = self.p.root / PAUSED_DIR_REL / name
            if path.exists():
                path.unlink()
        # A suffix the module constant does NOT ship, patched in for the duration.
        # Substituting the constant for its own literal value cannot change
        # behaviour, so a probe that did that was a no-op rather than a weak test;
        # changing what the constant HOLDS is what discriminates the binding from a
        # re-spelled literal.
        other = ".halted"
        (self.p.root / PAUSED_DIR_REL / f"{MECH}{other}").mkdir()
        with mock.patch.object(capability_health,
                               "GUARD_READ_MARKER_SUFFIXES", (other,)):
            self.assertEqual(
                capability_health._is_paused(self.p.root, MECH, (other,)),
                (True, False),
                "a guard-read marker of any shape must read as paused, because the "
                "wrapper's own `[ -e ]` test does -- with a re-spelled literal this "
                "falls into the regular-file branch and reports a read error "
                "instead")

    def test_per_capability_health_still_keys_on_the_PAIR(self):
        """The narrowing is scoped to the suppression surface. For "is this
        capability in a clean state", either file existing still means no."""
        self.assertEqual(
            capability_health._is_paused(self.p.root, MECH), (True, False))
        (self.p.root / PAUSED_DIR_REL / f"{MECH}.pause").unlink()
        self.assertEqual(
            capability_health._is_paused(self.p.root, MECH), (True, False),
            "a leftover .json still means the capability is not clean")
        self.assertEqual(
            capability_health._is_paused(
                self.p.root, MECH, capability_health.GUARD_READ_MARKER_SUFFIXES),
            (False, False),
            "but the guard would no longer fire")

    def test_the_route_refuses_a_bare_string_instead_of_rendering_characters(self):
        """A bare string is iterable, so it rendered one backtick-quoted CHARACTER
        per "path"."""
        with self.assertRaises(state_actions.StateActionError):
            state_actions.route_for_stale_pause_record(WRAPPER_REL, "some/path")

    def test_the_route_refuses_naming_no_file_at_all(self):
        with self.assertRaises(state_actions.StateActionError):
            state_actions.route_for_stale_pause_record(WRAPPER_REL, [])


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

    def test_the_refusal_and_the_actual_write_failure_AGREE_at_the_length_limit(self):
        """A refusal that says "fine" for an id the write then rejects is the
        installed-but-cannot-record gap at its far end.

        Measured before the bound existed: a 250-byte id recorded, 251 raised
        ``OSError: File name too long``, and the refusal answered ``None`` for both --
        so the sweep would have reported a tripwire installed for a mechanism that
        records nothing. Asserted as AGREEMENT rather than as a number: the id the
        refusal permits must record, and the one it refuses must be the one the
        filesystem would have rejected.
        """
        limit = suppressed_invocation.MAX_MECHANISM_ID_BYTES
        permitted, refused = "a" * limit, "a" * (limit + 1)

        self.assertIsNone(suppressed_invocation.mechanism_id_refusal(permitted))
        self.assertEqual(self._record(mechanism_id=permitted)["suppressed_count"], 1)

        reason = suppressed_invocation.mechanism_id_refusal(refused)
        self.assertIsNotNone(reason)
        self.assertIn("longer than this filesystem allows", reason)
        # and the refusal is not merely cautious -- the write genuinely fails.
        with self.assertRaises(suppressed_invocation.SuppressedInvocationError):
            self._record(mechanism_id=refused)
        with self.assertRaises(OSError):
            (Path(suppressed_invocation.events_dir(str(self.p.root)))
             / f"{refused}.json").write_text("x", encoding="utf-8")

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

    def test_a_suppression_with_no_open_item_still_names_a_PERFORMABLE_exit(self):
        """The blocking state whose exit used to say there wasn't one.

        This test previously asserted equality with
        ``route_for_unclassified_state`` -- i.e. it PINNED "this system has no
        recorded way out of it" as expected behaviour, for a condition that
        withholds the all-clear. A gate must never create a state the operator
        cannot leave, so that was the defect, not the spec.

        Asserted here against the properties an exit has to have, not against the
        call the code makes: it names the artifact holding the run, it names who
        can act, and it does not tell the operator there is no way out.
        """
        self._suppress(2)
        (entry,) = self._status()["suppressed_invocations"]["mechanisms"]
        action = entry["action"]
        self.assertNotIn("no recorded way out", action)
        self.assertIn(MECH, action, "the exit must name WHICH record holds the run")
        self.assertIn(PAUSED_DIR_REL, action,
                      "the exit must name WHERE that record is")
        self.assertIn(WRAPPER_REL, action, "and which run is stopped")
        self.assertIn("assistant", action, "the exit must name who can act")

    def test_that_exit_is_rendered_from_the_registry_not_composed_at_the_surface(self):
        """The monopoly rule still holds for the new route: the sentence comes from
        the registry, keyed on the same two values the surface has."""
        self._suppress(2)
        (entry,) = self._status()["suppressed_invocations"]["mechanisms"]
        self.assertEqual(
            entry["action"],
            state_actions.route_for_stale_pause_record(
                WRAPPER_REL, _pause_record_paths(MECH)))

    def test_the_stale_pause_route_does_not_claim_the_script_is_fixed(self):
        """This state is ALSO reachable for a writer whose item was never opened, so
        "your script now passes the check" would be false in that case. The route
        states the condition instead of asserting it."""
        route = state_actions.route_for_stale_pause_record(
            WRAPPER_REL, _pause_record_paths(MECH))
        self.assertIn("once they have confirmed", route)
        for false_claim in ("now passes the safety check and its item is closed",
                            "no action is needed"):
            self.assertNotIn(false_claim, route)

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

    def _unreadable_entry(self):
        self.p.pause_marker()
        path = Path(suppressed_invocation.event_path(str(self.p.root), MECH))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{truncated", encoding="utf-8")
        status = self._status()
        (bad,) = status["suppressed_invocations"]["unreadable"]
        return status, bad

    def test_an_unreadable_event_withholds_the_all_clear(self):
        status, bad = self._unreadable_entry()
        self.assertFalse(status["normal_status_allowed"], status)
        self.assertIn("truncated", Path(bad["path"]).read_text(encoding="utf-8"),
                      "the unreadable record must be left exactly as it is")

    def test_the_unreadable_routes_SENTENCE_IS_TRUE_for_this_record_kind(self):
        """Asserted against the FACTS, not against the same call the code makes.

        The previous version of this test compared `action` to
        `route_for_unidentified_record(path)` -- the identical call in the
        production line -- so it was a tautology: it pinned the code to itself and
        passed while the rendered sentence described **a trial run that does not
        exist** and warned that "a change that trial made may still be live on your
        real record". Nothing was changed; a suppressed run is one that did not
        happen. The branch withholds the all-clear, so that sentence was guaranteed
        to reach the operator.
        """
        _status, bad = self._unreadable_entry()
        action = bad["action"]
        self.assertIn(bad["path"], action)
        for false_claim in ("trial", "may still be live"):
            self.assertNotIn(
                false_claim, action,
                f"the sentence shown for an unreadable suppressed-invocation "
                f"record claims {false_claim!r}, which is not true of this record "
                f"kind:\n{action}")
        # It must still say the thing that IS true and is the reason it blocks.
        self.assertIn("stopped", action)

    def test_the_TRIAL_unreadable_branch_still_gets_the_TRIAL_route(self):
        """The other half of the same object, and the test whose absence let a real
        defect through.

        Adding a second unreadable-record route means TWO structurally similar call
        sites now sit in one function. The suppression assertion above pins one of
        them; nothing pinned the other, and the two got SWAPPED -- the trial surface
        told the operator about "scheduled runs that were stopped" and the
        suppression surface told them about "a trial run". Asserting one side of a
        pair proves nothing about the pair.
        """
        journal = self.p.root / "security" / "trial_runs"
        journal.mkdir(parents=True, exist_ok=True)
        (journal / "trial-broken.json").write_text("{nope", encoding="utf-8")
        status = self._status()
        (bad_trial,) = status["interrupted_trial"]["unreadable"]
        self.assertIn("trial", bad_trial["action"])
        self.assertIn("may still be live", bad_trial["action"],
                      "the trial route's warning is real for a trial and must not "
                      "be watered down to serve a second caller")
        self.assertNotIn("scheduled runs that were stopped", bad_trial["action"])

    def test_the_two_unreadable_record_routes_are_distinct_declarations(self):
        """Two callers needing two true sentences is two declared routes. A single
        shared string could only have been made true here by making it vaguer for
        the trial caller, which is the caller that legitimately needs the strong
        warning."""
        path = "some/record.json"
        self.assertNotEqual(
            state_actions.route_for_unreadable_suppression_record(path),
            state_actions.route_for_unidentified_record(path))
        self.assertIn("trial", state_actions.route_for_unidentified_record(path))
        self.assertNotIn(
            "trial",
            state_actions.route_for_unreadable_suppression_record(path))

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
