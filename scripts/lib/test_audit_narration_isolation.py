"""Isolation-validation net for the estate-close mutation-audit trail: proves
the redacted committable audit projection, the commit-hygiene guard, and the
honest bulk-run narration hold together, not just individually, over ONE real
PARTIAL bulk run -- some progress, a chunk refused, never finalized (the
honest hard case, not the clean-completion happy path already covered by
each module's own dedicated test file).

This file composes three already-landed, independently-tested behaviors:
  1. A redacted, committable audit projection of a run's durable records
     (``external_write.audit_projection.project_redacted_audit``) -- must
     carry zero raw per-item identifiers/subjects while still proving scale,
     consent, and an honest partial claim from the committed artifact alone.
  2. A commit-hygiene guard (``templates/claude_config/commit_hygiene.sh``)
     that auto-commits that redacted projection while never committing the
     raw records it was projected from, and does not abort when a
     newly-gitignored raw path gets untracked (a removal, never a content
     leak).
  3. An honest, typed-status-derived narration of the same run's outcome
     (``external_write.run_narration.render_bulk_run_outcome``) -- a partial
     run must read as unfinished, never as a completed success.

Each piece already has its own dedicated, exhaustive test file; this file
does NOT re-test their individual edge cases. It proves the THREE compose
correctly over one shared, realistic PII-shaped fixture, and pins two
genuine cross-module findings surfaced while composing them rather than
papering over them:
  * ``test_committed_claim_and_narrated_claim_use_different_scopes`` --
    the committed audit's overall claim and the narration's overall claim
    can read differently for the same run because each queries a
    differently-scoped slice of the durable recoverability report.
  * ``test_json_shaped_raw_record_pre_tracked_before_ignore_rule_is_not_caught``
    -- a raw record already tracked before its ignore rule existed is not
    reliably caught by the guard's already-tracked detection unless its
    extension is on the guard's built-in sensitive-pattern list.

Stdlib unittest; pip-install-free.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_AGENTS_LIB = _REPO_ROOT / "wizard" / "agents" / "lib"
sys.path.insert(0, str(_AGENTS_LIB))

from external_write import contracts as contracts_mod  # noqa: E402
from external_write.contracts import OperationContract  # noqa: E402
from external_write.adapter_registry import (  # noqa: E402
    register_adapter,
    unregister_adapter,
)
from external_write.read_facade import (  # noqa: E402
    ReadFacade,
    register_read_facade,
    unregister_read_facade,
)
from external_write.operations import Operation, EffectUnit  # noqa: E402
from external_write.run_envelope import (  # noqa: E402
    DEFAULT_ENVELOPE_DIR,
    RUN_STATE_EXECUTING,
    run_sanctioned_bulk,
)
from external_write.audit_projection import (  # noqa: E402
    DEFAULT_AUDIT_PROJECTION_DIR,
    RECOVERABLE_ALL,
    RECOVERABLE_PARTIAL,
    project_redacted_audit,
)
from external_write.run_narration import (  # noqa: E402
    BULK_RUN_PARTIAL,
    classify_bulk_run_status,
    render_bulk_run_outcome,
)

_COMMIT_HYGIENE = _REPO_ROOT / "wizard" / "templates" / "claude_config" / "commit_hygiene.sh"

_BASH = shutil.which("bash")
_GIT = shutil.which("git")
_HAVE_GIT_TOOLS = bool(_BASH) and bool(_GIT) and bool(shutil.which("python3"))

_FIELD_OP = "_isolation_field_probe"

# ---------------------------------------------------------------------------
# Fixture: a reversible field-write op-kind + a minimal client/adapter, and a
# realistic PII-shaped reviewed set large enough (30, chunked at 5) to hit a
# real aggregate approval ceiling mid-run -- a genuine, honest partial close,
# never a synthetic "pretend partial" flag.
# ---------------------------------------------------------------------------


def _register_field_contract():
    contracts_mod.OPERATION_CONTRACTS[_FIELD_OP] = OperationContract(
        op_kind=_FIELD_OP, writes=("Status",), produces=(), dependency_set=(),
        verifier_set=(), introduces_persistent_binding=False,
        risk_class="reversible_external", read_only_scope="fixture.readonly")


def _unregister_field_contract():
    contracts_mod.OPERATION_CONTRACTS.pop(_FIELD_OP, None)


def _op_builder(chunk_ids, value="Complete"):
    return Operation(
        surface="fixture_surface", op_kind=_FIELD_OP, batch_id="isolation-bulk",
        params={"rows": [{"row_id": uid, "intended_value": value} for uid in chunk_ids]})


class _FieldWriteClient:
    def __init__(self, store):
        self._store = store

    def write_row(self, row_id, value):
        self._store[row_id] = {"value": value}


class _FieldReadOnlyClient:
    def __init__(self, store):
        self._store = store

    def read_row(self, row_id):
        return dict(self._store.get(row_id, {}))


class _FieldReadFacade(ReadFacade):
    read_methods = ("read_row",)

    def read_row(self, row_id):
        return self._read("read_row", row_id)


class _FieldAdapter:
    def plan(self, params):
        params = params or {}
        return [EffectUnit(unit_id=r["row_id"], target_ref=r)
                for r in params.get("rows", [])]

    def apply_one(self, raw_client, unit):
        raw_client.write_row(unit.unit_id, unit.target_ref["intended_value"])

    def undo_one(self, raw_client, unit):
        pass

    def verify_one(self, observer, unit):
        observed = observer.read_row(unit.unit_id)
        return {"value": observed.get("value"),
                "intended_value": unit.target_ref["intended_value"]}

    def verify_apply_landed(self, evidence):
        return evidence.poststate.get("value") == evidence.poststate.get("intended_value")


# Realistic-looking, PII-shaped raw values -- realistic per-item identifiers,
# a name, an email address, and a shared account id, plus the secret
# operator-utterance text itself. These must NEVER survive into the
# committed, redacted audit artifact.
_PII_NAME = "Jane Q. Doe"
_PII_EMAIL = "jane.doe.private@example.com"
_PII_ACCOUNT_ID = "acct-9284710"
_PII_UTTERANCE = (
    "yes, go ahead and update the status on all thirty of the flagged rows "
    f"tied to {_PII_EMAIL}, account {_PII_ACCOUNT_ID}"
)
_POPULATION = 30
_CHUNK_SIZE = 5


def _pii_unit_id(i):
    return f"18f2a9c7b3d4e{500 + i:03x}"


def _pii_reviewed_set(n):
    return [
        {
            "unit_id": _pii_unit_id(i),
            "prestate_digest": f"d{i}",
            "intended_mutation": {
                "value": "Complete",
                "subject": f"Re: Wire transfer confirmation #{i} - {_PII_NAME}",
                "from_address": _PII_EMAIL,
                "account_id": _PII_ACCOUNT_ID,
            },
            "category": "status_change", "protected_status": False,
        }
        for i in range(n)
    ]


_PII_RAW_VALUES = tuple(
    [_pii_unit_id(i) for i in range(_POPULATION)]
    + [_PII_NAME, _PII_EMAIL, _PII_ACCOUNT_ID, _PII_UTTERANCE,
       "Wire transfer confirmation"]
)


def _run_partial_bulk(*, envelope_dir=None, ledger_dir=None, receipt_dir=None):
    """A real ``run_sanctioned_bulk`` call over the PII-shaped 30-row
    reviewed set at a 5-row chunk size -- reversible tier, so the aggregate
    approval ceiling clamps to 25: five chunks apply, the sixth is refused
    BEFORE it writes. A real, honest partial: real progress, never
    finalized, a chunk genuinely refused -- never a synthetic status flag."""
    reviewed_set = _pii_reviewed_set(_POPULATION)
    store = {e["unit_id"]: {"value": "Open"} for e in reviewed_set}
    return run_sanctioned_bulk(
        op_builder=_op_builder, run_label="estate-partial-close",
        capability_id="cap:test", op_kind=_FIELD_OP,
        contract_hash="ch-iso", implementation_hash="ih-iso",
        reviewed_set=reviewed_set,
        operator_approval_verbatim=_PII_UTTERANCE,
        consent_sentence_shown="Apply the reviewed status changes.",
        approved_at="2026-07-19T22:45:48Z",
        chunk_size=_CHUNK_SIZE, envelope_dir=envelope_dir,
        ledger_dir=ledger_dir, receipt_dir=receipt_dir,
        client=_FieldWriteClient(store), read_only_client=_FieldReadOnlyClient(store))


class ClusterCloseIsolationTests(unittest.TestCase):
    """Runs ONE real partial bulk run per test (inside a throwaway cwd so the
    real DEFAULT on-disk paths -- ``security/run_envelopes/``,
    ``security/invocation_ledgers/``, ``security/audit/`` -- are exercised,
    matching how an operator project actually lays these out), then exercises
    the redacted-projection / commit-guard / narration behaviors against that
    one run's on-disk state."""

    def setUp(self):
        _register_field_contract()
        register_read_facade(_FIELD_OP, _FieldReadFacade)
        register_adapter(_FIELD_OP, _FieldAdapter())
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self._orig_cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()
        _unregister_field_contract()
        unregister_adapter(_FIELD_OP)
        unregister_read_facade(_FIELD_OP)

    # -- git helpers (only used by the commit-guard test below) ------------

    def _git(self, *args):
        return subprocess.run(
            [_GIT, "-C", str(self.repo), *args], capture_output=True, text=True)

    def _tracked(self):
        return set(self._git("ls-files").stdout.split())

    def _tree_at_head(self):
        out = self._git("ls-tree", "-r", "--name-only", "HEAD").stdout
        return set(f for f in out.split() if f)

    def _head(self):
        return self._git("rev-parse", "HEAD").stdout.strip()

    def _run_hook(self, event):
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.repo)}
        return subprocess.run(
            [_BASH, str(_COMMIT_HYGIENE)],
            input=json.dumps({"hook_event_name": event}),
            capture_output=True, text=True, cwd=str(self.repo), env=env)

    # -----------------------------------------------------------------------
    # 1. Redacted audit of the partial run.
    # -----------------------------------------------------------------------

    def test_redacted_audit_of_partial_run_hides_pii_and_reports_honest_state(self):
        summary = _run_partial_bulk()
        # Sanity: this really is the honest hard case -- real progress, a
        # chunk genuinely refused, never finalized.
        self.assertTrue(summary.refused, summary.refusal_reason)
        self.assertFalse(summary.finalized)
        self.assertEqual(len(summary.applied_unit_ids), 25)

        result = project_redacted_audit(
            summary.run_id, system_version="sys-test", bundle_version="v-test",
            git_version="deadbeef")
        serialized = json.dumps(result.projection)

        # (a) zero raw ids/subjects/PII survive into the committed projection.
        for raw in _PII_RAW_VALUES:
            self.assertNotIn(
                raw, serialized,
                f"PII-shaped raw value leaked into the redacted audit projection: {raw!r}")

        # (b) honest partial counts + claim-level + the ONE run-level consent
        # digest + the real operator-utterance timestamp.
        p = result.projection
        self.assertEqual(p["run_id"], summary.run_id)
        self.assertEqual(p["reviewed_set_count"], _POPULATION)
        self.assertEqual(p["counts_by_status"]["applied"], 25)
        self.assertEqual(p["recovery_manifest_count"], 25)
        self.assertTrue(p["consent_receipt_digest"])
        self.assertEqual(p["consent_timestamp"], "2026-07-19T22:45:48Z")
        self.assertEqual(p["run_state"], RUN_STATE_EXECUTING)  # never finalized
        self.assertIn(p["claim_level"], (RECOVERABLE_ALL, RECOVERABLE_PARTIAL))

        # (c) written to the committable security/audit/ path (the real
        # default -- no audit_dir override given above).
        self.assertEqual(
            str(Path(result.path).parent), DEFAULT_AUDIT_PROJECTION_DIR)
        on_disk = json.loads(Path(result.path).read_text(encoding="utf-8"))
        self.assertEqual(on_disk, result.projection)

        # A reviewer with ONLY the committed artifact can still prove scale +
        # consent + honesty about the partial state -- no access to the raw
        # envelope needed.
        committed_only = json.loads(Path(result.path).read_text(encoding="utf-8"))
        self.assertEqual(committed_only["reviewed_set_count"], _POPULATION)
        self.assertTrue(committed_only["consent_receipt_digest"])
        self.assertNotEqual(committed_only["run_state"], "finalized")

    # -----------------------------------------------------------------------
    # 2. Durable + privacy-safe close: the commit-hygiene guard over the
    #    partial run's real on-disk raw + redacted state.
    # -----------------------------------------------------------------------

    def _seed_baseline(self, *, with_canonical_gitignore):
        # `git status` collapses an entirely-new, never-tracked directory
        # into a single "?? dirname/" record instead of enumerating its
        # contents -- so a from-scratch temp repo must seed a tracked
        # baseline file under security/ FIRST, exactly as the wizard's real
        # project scaffold does at project close (security/README.md),
        # before any run or ignore rule ever touches that directory.
        # Otherwise later individual files under security/ (the audit
        # projection, a raw record) get reported as one indistinct blob the
        # guard cannot positively classify -- an artifact of this test's own
        # from-scratch fixture, not the guard's real per-file behavior.
        self._git("init", "-q")
        self._git("config", "user.email", "t@t.test")
        self._git("config", "user.name", "Test")
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        (self.repo / "security").mkdir(exist_ok=True)
        (self.repo / "security" / "README.md").write_text("sec\n", encoding="utf-8")
        to_add = ["README.md", "security/README.md"]
        if with_canonical_gitignore:
            # The real, canonical ignore patterns for the raw-record classes,
            # scaffolded BEFORE any run ever happens -- the real operational
            # order (the wizard writes .gitignore at project close, long
            # before an operator's first bulk run).
            (self.repo / ".gitignore").write_text(
                "/security/acceptance_receipts/\n"
                "/security/run_envelopes/\n"
                "/security/invocation_ledgers/\n"
                "/security/capability_acceptance_log.jsonl\n",
                encoding="utf-8")
            to_add.append(".gitignore")
        self._git("add", *to_add)
        self._git("commit", "-q", "-m", "baseline")

    @unittest.skipUnless(_HAVE_GIT_TOOLS, "bash / git / python3 unavailable")
    def test_commit_guard_commits_redacted_audit_and_never_stages_raw_records(self):
        self._seed_baseline(with_canonical_gitignore=True)

        summary = _run_partial_bulk()
        envelope_path = f"{DEFAULT_ENVELOPE_DIR}/{summary.run_id}.json"
        consent_receipt_path = f"{DEFAULT_ENVELOPE_DIR}/{summary.run_id}.consent_receipt.json"
        self.assertTrue((self.repo / envelope_path).is_file())
        self.assertTrue((self.repo / "security" / "invocation_ledgers").is_dir())

        # Two further raw-record categories this particular run does not
        # itself produce, seeded so the guard's FULL privacy surface (not
        # just what this one op-kind happens to write) is exercised.
        (self.repo / "security" / "acceptance_receipts").mkdir(parents=True)
        (self.repo / "security" / "acceptance_receipts" / "cap-test.receipt.json").write_text(
            "{}\n", encoding="utf-8")
        (self.repo / "security" / "capability_acceptance_log.jsonl").write_text(
            "{}\n", encoding="utf-8")

        # The redacted, committable audit projection of this same run,
        # alongside the raw records it was projected from.
        result = project_redacted_audit(summary.run_id)
        audit_path = str(Path(result.path))

        before = self._head()
        r = self._run_hook("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)  # never aborts
        after = self._head()
        self.assertNotEqual(before, after, "guard made no commit for the partial run's close")

        tracked = self._tracked()
        tree = self._tree_at_head()

        # Durable: the redacted projection is committed.
        self.assertIn(audit_path, tracked)
        self.assertIn(audit_path, tree)

        # Privacy-safe: every raw-record category was never staged or
        # committed -- gitignored from before it ever existed on disk.
        for raw in (
            envelope_path, consent_receipt_path,
            "security/acceptance_receipts/cap-test.receipt.json",
            "security/capability_acceptance_log.jsonl",
        ):
            self.assertNotIn(raw, tracked, f"raw record was committed: {raw}")
            self.assertNotIn(raw, tree, f"raw record ended up in the commit tree: {raw}")
            self.assertTrue((self.repo / raw).exists(), f"working file missing: {raw}")

    @unittest.skipUnless(_HAVE_GIT_TOOLS, "bash / git / python3 unavailable")
    def test_untracking_a_now_gitignored_raw_record_does_not_abort_the_guard(self):
        # The estate's real shape: a raw record gets tracked BEFORE its
        # ignore rule exists. Use the acceptance-log category here -- its
        # ".jsonl" extension is on the guard's BUILT-IN sensitive-pattern
        # list (checked independently of git-ignore state), so the guard's
        # already-tracked detection genuinely fires and untracks it (a `D`),
        # proving that untracking a sensitive path never aborts the guard.
        self._seed_baseline(with_canonical_gitignore=False)

        summary = _run_partial_bulk()
        log_path = "security/capability_acceptance_log.jsonl"
        (self.repo / log_path).write_text(
            json.dumps({"run_id": summary.run_id, "event": "capability_accepted"}) + "\n",
            encoding="utf-8")
        self._git("add", log_path)
        self._git("commit", "-q", "-m", "acceptance log tracked before an ignore rule existed")
        self.assertIn(log_path, self._tracked())

        (self.repo / ".gitignore").write_text(
            "/security/capability_acceptance_log.jsonl\n", encoding="utf-8")
        result = project_redacted_audit(summary.run_id)
        audit_path = str(Path(result.path))

        before = self._head()
        r = self._run_hook("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)  # never aborts
        after = self._head()
        self.assertNotEqual(before, after, "the untracking + audit commit did not land")

        tracked = self._tracked()
        tree = self._tree_at_head()
        self.assertNotIn(log_path, tracked, "the now-gitignored log was left tracked")
        self.assertNotIn(log_path, tree, "the untracked log's content is still in the commit tree")
        self.assertIn(audit_path, tracked, "the redacted audit was not committed alongside the untracking")
        # Working file is preserved (untracked via rm --cached, never deleted).
        self.assertTrue((self.repo / log_path).exists())
        # Surfaced, never silent.
        out = r.stdout + r.stderr
        self.assertIn(log_path, out)
        self.assertIn("histor", out.lower())

    @unittest.skipUnless(_HAVE_GIT_TOOLS, "bash / git / python3 unavailable")
    def test_json_shaped_raw_record_pre_tracked_before_ignore_rule_is_not_caught(self):
        """Composition finding, pinned rather than silently papered over: a
        raw run-envelope record (a plain ``.json`` file, extension-neutral)
        that somehow got committed BEFORE its ignore rule existed is NOT
        caught by the guard's already-tracked detection. ``git check-ignore``
        never reports an already-tracked path as ignored regardless of the
        ignore rule (a documented git limitation, not a scanning bug), and a
        bare run-envelope/ledger/acceptance-receipt ``.json`` is not on the
        guard's BUILT-IN sensitive-pattern list either (unlike the
        ``.jsonl`` acceptance log, see the sibling test above) -- so this
        specific raw-record family has no independent detection path once
        already tracked. In the wizard's real operational order (the
        ignore rule is scaffolded before any run ever happens) this gap is
        not reached; it only matters for a repo whose ignore rule postdates
        an existing tracked raw record. Flagged for follow-up; no
        production code is changed by this test-only net.
        """
        self._git("init", "-q")
        self._git("config", "user.email", "t@t.test")
        self._git("config", "user.name", "Test")
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-q", "-m", "baseline")

        summary = _run_partial_bulk()
        envelope_path = f"{DEFAULT_ENVELOPE_DIR}/{summary.run_id}.json"
        self._git("add", DEFAULT_ENVELOPE_DIR)
        self._git("commit", "-q", "-m", "raw envelope tracked before an ignore rule existed")
        self.assertIn(envelope_path, self._tracked())

        (self.repo / ".gitignore").write_text(f"/{DEFAULT_ENVELOPE_DIR}/\n", encoding="utf-8")
        r = self._run_hook("SessionEnd")
        self.assertEqual(r.returncode, 0, r.stderr)  # still never aborts

        # Pinning the OBSERVED gap: the pre-tracked raw record remains
        # tracked and in the commit tree even after the guard runs.
        self.assertIn(envelope_path, self._tracked())
        self.assertIn(envelope_path, self._tree_at_head())

    # -----------------------------------------------------------------------
    # 3. Honest narration of the same partial run.
    # -----------------------------------------------------------------------

    def test_narration_of_partial_run_is_honest_never_a_completed_success(self):
        summary = _run_partial_bulk()
        self.assertEqual(classify_bulk_run_status(summary), BULK_RUN_PARTIAL)

        text = render_bulk_run_outcome(summary)
        self.assertIn("PARTIAL", text)
        self.assertNotIn("COMPLETED", text)
        self.assertNotIn("REFUSED", text)
        # The COMPLETED branch's own success phrase must never appear here.
        self.assertNotIn("finalized. ", text)
        self.assertIn("has NOT finished", text)
        self.assertEqual(len(summary.applied_unit_ids), 25)
        self.assertIn("25 item(s) applied this call", text)

        # "Recoverable" is asserted ONLY per the durable recoverability
        # report already attached to the summary -- never invented here.
        counts = summary.recoverability["counts"]
        self.assertIn(
            f"Recoverable by this system: {counts['recoverable_by_system']}", text)
        self.assertIn(
            f"NOT recoverable by this system: {counts['not_recoverable_by_system']}", text)

    # -----------------------------------------------------------------------
    # 4. Coherence: the committed audit's claim vs. the narration's claim,
    #    for the SAME run.
    # -----------------------------------------------------------------------

    def test_committed_claim_and_narrated_claim_use_different_scopes(self):
        """Both the committed audit projection's ``claim_level`` and the
        narration's rendered "Overall recoverability" line use the exact
        same three-way vocabulary, computed by the exact same underlying
        classification helper (the narration module imports it from the
        audit-projection module rather than re-deriving it) over the exact
        same durable recoverability report for this run -- but each reads a
        DIFFERENTLY SCOPED query into that report:

          * the audit projection deliberately narrows its query to only the
            ids this run actually applied (25) -- by its own documented
            design, so a never-applied, still-reviewed id never dilutes the
            claim about what was actually mutated;
          * the narration reads the run's own attached recoverability
            report, which is queried over the full reviewed-union-applied
            set (30) -- folding the 5 never-applied, ceiling-refused ids in
            as "not recoverable".

        For THIS run those two scopes disagree on the headline claim: the
        committed, durable artifact reads "every applied item is
        recoverable" while the narration reads "part of the whole plan is
        recoverable" -- both individually honest against their own stated
        scope, but presenting differently to a reader who sees only one of
        the two. This test pins that observed disagreement precisely (rather
        than asserting a false agreement) as a genuine composition finding
        for this close to resolve -- it is not a defect in either module
        read alone, and no production code is changed here.

        What DOES agree, because both figures trace back to the SAME durable
        tranche records: the raw count of ids provably recoverable.
        """
        summary = _run_partial_bulk()
        result = project_redacted_audit(summary.run_id)
        text = render_bulk_run_outcome(summary)

        narrated_claim = text.strip().splitlines()[-1].rstrip(".").rsplit(": ", 1)[-1]
        committed_claim = result.projection["claim_level"]

        self.assertEqual(committed_claim, RECOVERABLE_ALL)
        self.assertEqual(narrated_claim, RECOVERABLE_PARTIAL)
        self.assertNotEqual(
            committed_claim, narrated_claim,
            "the committed-audit claim and the narrated claim now AGREE for a "
            "partial run where they previously diverged by scope -- if this is "
            "an intentional fix to align the two scopes, update this test to "
            "pin the new (agreeing) behavior; if it is accidental, investigate "
            "before treating it as a passing coherence check")

        self.assertEqual(
            result.projection["counts_by_status"]["recoverable_by_system"],
            summary.recoverability["counts"]["recoverable_by_system"])


if __name__ == "__main__":
    unittest.main()
