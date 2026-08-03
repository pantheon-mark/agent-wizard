"""The trust-zone taxonomy — SINGLE canonical place both ``scan.py`` (the AST
bypass scanner) and ``coverage_gate.py`` (the descriptor-coverage gate) read
to decide which trust zone a module belongs to (Task 5 —
external-write-gate-generalization slice).

------------------------------------------------------------------------------
Why a three-zone split (replaces the old "whole external_write/ tree is
exempt" rule)
------------------------------------------------------------------------------
Prior to this task, ``scan.py`` exempted every file inside the installed
``agents/lib/external_write/`` directory from every bypass check — one
binary distinction (inside the package == trusted; outside == scanned in
full). That was fine while the package held only the surface-agnostic gate
machinery, but it does not survive the package growing concrete, per-vendor
adapter modules: those modules MUST legitimately import a vendor SDK, obtain
a write-capable credential, and perform raw vendor mutation, while every
OTHER module in the package must NOT be able to do any of those three
things. A single "inside the package" exemption cannot express that split.

So the trust boundary is split into three zones:

  SEALED_KERNEL    -- the gate machinery itself: ``run_operation`` (in
                      adapters.py), the write gate + invocation ledger (in
                      write_gate.py), the broker, receipt validation, the
                      operation/contract/proof-hash/effects-manifest layers,
                      the adapter registry, the read facade, the AST scanner
                      and coverage gate, and the acceptance/verification
                      support modules. This code is surface-agnostic by
                      design (see contracts.py, operations.py) and must
                      NEVER need a vendor SDK import or a write-capable
                      credential. It is therefore held to the SAME bypass
                      checks as ordinary capability code (forbidden_import,
                      direct_api_call, dynamic_import, subprocess_network,
                      credential_construction) -- it is not a free pass, it
                      simply never trips them because it never needs to.

  ADAPTER_PROFILE   -- registered, per-vendor adapter modules (e.g. the
                      eventual Gmail/Sheets/etc. adapter modules -- Task 7+).
                      This is the ONLY zone allowed to import a vendor SDK,
                      construct/obtain a write-capable credential, and
                      perform raw vendor mutation. It is exempt from every
                      check scan.py enforces.

  CAPABILITY        -- everything else: operator capability/proposal/read
                      scripts, and -- critically -- any module that is not
                      EXPLICITLY enumerated in either allowlist below, even
                      if it physically lives inside the installed package
                      directory. This is the fail-closed default: an
                      unclassifiable module is always treated as the most
                      restrictive zone, never silently granted a pass.

------------------------------------------------------------------------------
Zone membership is EXPLICIT, never "anything under this path"
------------------------------------------------------------------------------
A prior review of this gate's history flagged exactly this failure mode
once already (see scan.py's "Allowed-module identity" section: exemption
used to be keyed on a directory NAME appearing anywhere in the path, which
was spoofable). This task removes a SECOND, more subtle version of the same
failure mode: if adapter-profile membership were decided by "any file under
external_write/adapters/", a newly created adapter directory would be
blanket-exempted from every check the moment it exists, before a human ever
looked at what is inside it -- the exact bug class this taxonomy exists to
prevent, one level down.

Both allowlists below are therefore enumerated by RELATIVE PATH (from the
kernel anchor), not by directory membership. A file is SEALED_KERNEL or
ADAPTER_PROFILE iff (a) it resolves to a location under the anchor AND (b)
its path relative to the anchor is literally listed in the corresponding
frozenset. Adding a new file under the package directory does not exempt it
from anything until its relative path is deliberately added to one of these
sets -- and doing that is a reviewable, textual, one-line diff.

Stdlib only -- no third-party dependencies.
"""

import json
from enum import Enum
from pathlib import Path
from typing import FrozenSet, Optional, Union


class Zone(Enum):
    """The three trust zones. See module docstring."""

    SEALED_KERNEL = "sealed_kernel"
    ADAPTER_PROFILE = "adapter_profile"
    CAPABILITY = "capability"


# ---------------------------------------------------------------------------
# SEALED_KERNEL -- the gate machinery. Enumerated explicitly (relative path
# from the package anchor), not "everything in this directory". Every file
# that currently exists in agents/lib/external_write/ is gate machinery (no
# concrete adapter module has landed yet -- that is Task 7+), so this list is,
# for now, the complete file listing of the installed package; it does NOT
# grow automatically when a new file is added (see module docstring).
# ---------------------------------------------------------------------------
SEALED_KERNEL_MODULE_PATHS: FrozenSet[str] = frozenset(
    {
        "__init__.py",
        "acceptance_ceremony.py",
        "adapter_registry.py",
        "adapters.py",
        "boundary.py",
        "broker.py",
        # capability_invariants.py (Task B1, F-74 — Cut 1.1 Cluster B): the
        # emitted self-QA / next-phase Step-4 battery. Before this task it
        # needed NO exemption from anything scan.py enforces (see its own
        # module docstring's now-superseded "Zone note") -- it never
        # referenced the adapter registry's internals. B1 changes that: Check
        # 7 must read a capability's registered adapter's dispatch record
        # (`adapter_registry.get_dispatch`) to verify it declares the
        # REQUIRED evidence predicates (`evidence.REQUIRED_EVIDENCE_
        # PREDICATES`) -- the SAME read-only inspection
        # `operator_acceptance.py`/`acceptance_ceremony.py` (both already
        # SEALED_KERNEL) already perform legitimately for the identical
        # reason. This is a READ of the dispatch record only -- this module
        # still never imports a vendor SDK, constructs/obtains a
        # write-capable credential, or calls `run_operation` -- so it is held
        # to the SAME bypass checks as before (see the module docstring above
        # for what SEALED_KERNEL membership does and does not exempt); it is
        # exempt ONLY from the four CAPABILITY-zone-ONLY rules
        # (adapter_module_import / adapter_registry_reference /
        # introspection_escape_hatch / raw_run_operation_reference), the same
        # exemption `registered_adapters.py`'s entry below already documents
        # for the identical reason.
        "capability_invariants.py",
        "capability_registration.py",
        # capability_runner.py (Task 5 / Cut 1.6 — v0.20.0): the kernel-as-runner
        # that resolves a capability's adapter, builds its READ-ONLY client, and
        # injects the resulting facade — so capability code never bootstraps a
        # client and never has a reason to import the adapter (F-VAL19-5). It
        # legitimately reaches the adapter registry (`get_dispatch`) and imports
        # capability/adapter modules by name, which are precisely the
        # CAPABILITY-zone-only bans, so it needs the same SEALED_KERNEL
        # membership registered_adapters.py already carries for the identical
        # reason. It builds no WRITE credential and never calls run_operation.
        "capability_runner.py",
        "contracts.py",
        "copy_run_proof.py",
        "coverage_gate.py",
        "effects_manifest.py",
        "operations.py",
        "operator_acceptance.py",
        "proof_hash.py",
        "read_facade.py",
        # registered_adapters.py (Task 7 / F-37 — v0.13.0 Slice 2): the
        # build-emitted static adapter registry `operator_acceptance.py`
        # imports at module scope so the operator-acceptance CLI is turnkey.
        # It exists SOLELY to import adapter modules (adapters_gmail.py, and
        # any capability-added adapters_<id>.py) at module scope -- exactly
        # the "registry's own intended kernel-side consumer" rationale
        # already given for adapters.py/effects_manifest.py above, so it is
        # exempt from the CAPABILITY-zone-ONLY adapter_module_import rule the
        # same way they are.
        "registered_adapters.py",
        # run_envelope.py — the v0.12.0 RunEnvelope trust core. It legitimately
        # wraps the raw kernel primitive run_operation (the ONE place the
        # run-level envelope — disk-authoritative spendability, consent-receipt
        # binding, APPLY-BY-ID against the frozen reviewed_set, and the
        # AGGREGATE CEILING — is enforced around it). It is kernel machinery,
        # exactly like adapters.py / write_gate.py, so it belongs in
        # SEALED_KERNEL and is exempt from the CAPABILITY-zone-ONLY
        # raw_run_operation_reference rule scan.py enforces (a capability
        # module reaching run_operation directly would bypass that envelope).
        "run_envelope.py",
        "scan.py",
        "verification_modes.py",
        "verifiers.py",
        # writer_acknowledgement.py (Task 3 / Cut 1.6 — v0.20.0): records the
        # operator's accepted-risk decision for an unrepairable bespoke writer,
        # the ONE sanctioned exit from WriterState.NEEDS_PERSON. It WRITES
        # project state (security/bespoke_writer_acknowledgements.json) and
        # reads a sibling kernel submodule, making it ordinary internal kernel
        # wiring — the same class as _ext_write_state.py / lifecycle_state.py,
        # which carry this membership for the identical reason. It imports no
        # vendor SDK, constructs no credential, and never calls run_operation,
        # so it is exempt ONLY from the four CAPABILITY-zone-only rules; every
        # universal bypass check still binds.
        "writer_acknowledgement.py",
        "write_gate.py",
        "zones.py",
        # standing_automation.py (Task 9 / B2 / F-42 — v0.13.0 Slice 2): the safe
        # standing-automation entrypoint primitive. Its --check/--dry-run path
        # legitimately calls raw `run_operation(..., target="dry_run")` — reusing
        # the SAME code path a live run eventually uses rather than a separate
        # fake check surface (the operator-originated-enhancement flow's
        # pre-acceptance test-surface amendment) — so it needs the
        # same SEALED_KERNEL exemption from the CAPABILITY-zone-ONLY
        # raw_run_operation_reference rule that run_envelope.py already carries
        # (see that entry's rationale above). It never authorizes or performs a
        # LIVE write itself (the live branch calls the caller-supplied
        # `run_live`, never `run_operation`), so it does not need — and does not
        # get — the ADAPTER_PROFILE exemption.
        "standing_automation.py",
        # The following eight files (v0.16.0 Cut 1.2 — A' / V15-3b) are
        # deterministic, non-vendor, non-credential kernel support modules
        # added to the package over time without ever being added to this
        # registry — harmless under the OLD CAPABILITY-zone-only rules
        # (adapter_module_import / adapter_registry_reference /
        # introspection_escape_hatch / raw_run_operation_reference) because
        # none of them happens to trip those narrow, symbol-specific checks.
        # The NEW `sealed_kernel_import` module-boundary rule this task adds
        # is broader BY DESIGN (any external_write submodule import outside
        # the small operator-facing allowlist, not just a few named symbols),
        # so it is the first rule to expose this pre-existing registry gap:
        # each of these files legitimately imports from OTHER kernel
        # submodules (contracts, run_envelope, broker, capability_identity,
        # lifecycle_state, operator_acceptance, proof_hash,
        # acceptance_ceremony, audit_projection, ...) as ordinary internal
        # kernel wiring, which is exactly the SEALED_KERNEL exemption
        # this registry exists to grant by explicit, reviewable listing —
        # none imports a vendor SDK, constructs/obtains a write-capable
        # credential, or performs a raw vendor mutation.
        #   capability_api.py — the curated capability-facing re-export shim
        #     (see its own module docstring); internally imports
        #     run_enveloped_operation/run_sanctioned_bulk from run_envelope.py
        #     to build that re-export. This SEALED_KERNEL entry newly exempts
        #     it from every CAPABILITY-zone-ONLY check (adapter_module_import
        #     / adapter_registry_reference / introspection_escape_hatch /
        #     raw_run_operation_reference / sealed_kernel_import), same as
        #     any other SEALED_KERNEL member -- it already passed all of
        #     those on its own merits before this entry existed (it is
        #     deliberately thin: two imports, one re-export list, no logic),
        #     so nothing it was previously relying on the CAPABILITY-zone
        #     checks to enforce changes here.
        #   audit_projection.py, bulk_verify.py, capability_health.py,
        #     consent_narration.py, evidence.py, lifecycle_state.py,
        #     run_narration.py — mechanism-only kernel support modules (audit
        #     projection, bulk-verify tooling, capability health checks,
        #     consent narration, evidence predicates, capability lifecycle
        #     state, and run-outcome narration, respectively); see each
        #     file's own "Why this exists" docstring section.
        "audit_projection.py",
        "bulk_verify.py",
        "capability_api.py",
        "capability_health.py",
        "consent_narration.py",
        "evidence.py",
        # _ext_write_state.py (Cut 1.5 / v0.19.0, Task B): the open-bespoke-writer
        # bypass predicate (Task A) PLUS the stateless auto-reap (Task B) that
        # REWRITES agents/handoffs/pending_migrations.json to remove a resolved
        # writer entry, and imports the sibling scanner (external_write.scan) to
        # get the writer's real (non-quarantined) verdict. That makes it ordinary
        # internal kernel wiring of the SAME class as lifecycle_state.py below
        # (which also mutates the descriptor set / pause markers / this same
        # queue) -- so it is listed here by decision, not left CAPABILITY-clean
        # by accident of the name-form import gap. It imports no vendor SDK,
        # constructs/obtains no write-capable credential, performs no raw vendor
        # mutation, and never calls run_operation -- so, exactly like every other
        # entry in this V15-3b group, it passes every universal bypass check on
        # its own merits and needs exemption ONLY from the CAPABILITY-zone-ONLY
        # rules. SEALED_KERNEL membership does NOT grant a capability the right to
        # import it (that allowlist is the independent
        # scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES set).
        "_ext_write_state.py",
        "lifecycle_state.py",
        "run_narration.py",
        # dependency_enrollment.py (Cut 1.4 Task 5 / F-9, review fix): capability
        # third-party dependency enrollment -- resolves/pins a vendor package,
        # records it in operator_requirements.json, re-renders requirements.txt,
        # and installs it into the project's own .venv/. It shells out to pip
        # (`pip index versions`, `pip install`, `pip freeze` via `subprocess`) --
        # a REAL network reach -- which is exactly the shape a CAPABILITY-zone
        # module must never be allowed (see this module's own docstring: the
        # CAPABILITY-zone-ONLY checks scan.py enforces exist precisely to stop
        # an ungated network reach like this one). Before this entry existed,
        # dependency_enrollment.py scanned clean under the OLD rules by
        # ACCIDENT, not by decision: scan.py's subprocess_network check only
        # flags a shell-out that names a known network CLI tool
        # (_NETWORK_CLI_TOOLS -- curl/wget/scp/...), and "pip" was never added
        # to that list, so the module happened to pass regardless of its zone.
        # This is a deliberate, reviewed decision that it is TRUSTED build/
        # maintenance infrastructure, not operator-facing capability code that
        # writes to the operator's external (vendor) surface: it manages the
        # project's OWN Python environment (.venv/requirements.txt), never a
        # customer/vendor mutation, and every capability's actual vendor write
        # still goes through the ordinary adapter/broker/write_gate path this
        # zone protects -- so it is SEALED_KERNEL, not ADAPTER_PROFILE (that
        # zone is reserved for per-vendor WRITE adapters that mutate the
        # operator's external surface, which this module never does) and not
        # left CAPABILITY (the fail-closed default, which would make its own
        # network reach look like an ordinary, ungated capability bypass the
        # next time scan.py's denylist is tightened to include "pip" -- a
        # separate, deliberately deferred follow-up; see this module's own
        # docstring section on the pip subprocess reach for why it does not
        # import a raw HTTP client instead).
        #
        # SEALED_KERNEL membership does NOT grant a capability the right to
        # import it: the CAPABILITY-zone import allowlist
        # (`scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES`) is the
        # independent, narrow {capability_api, operations, read_facade} set --
        # a capability importing `external_write.dependency_enrollment`
        # directly is already a `sealed_kernel_import` violation under the
        # existing A' module-boundary rule, exactly like capability_health.py
        # (see test_sealed_kernel_membership_does_not_grant_capability_zone_
        # import / test_capability_zone_importing_dependency_enrollment_is_
        # flagged in test_external_write_scan.py). It is invoked ONLY by the
        # build agent's own CLI call, never imported by emitted capability code.
        "dependency_enrollment.py",
        # test_capability_runner_topology.py: kernel-side tests of
        # capability_runner.py's own read-facade resolution. It legitimately
        # imports `external_write.topology` directly -- constructing
        # `TopologyError` with known attributes and, in one test, replacing
        # `Topology.find_read_facade` for the duration of a single test -- to
        # prove the kernel classifies a resolution failure purely from the
        # exception's own attributes rather than re-deriving the
        # classification itself. `topology` is not in the CAPABILITY-zone
        # import allowlist, so this needs the same membership
        # capability_runner.py itself already carries for the identical
        # reason: it is kernel-internal test code, never emitted capability
        # code, and it imports no vendor SDK, constructs no credential, and
        # never calls run_operation.
        "test_capability_runner_topology.py",
        # trial_eligibility.py (Cut 1.9 Task 1 / v0.23.0): the trial-eligibility
        # preflight -- the fail-closed gate that decides which operations may
        # legally undergo a journaled apply/verify/undo/verify-restored TRIAL,
        # evaluated BEFORE any external write. It imports the sibling kernel
        # `adapter_registry` (for `get_dispatch` + the canonical declaration
        # attribute name) and `evidence` (for the canonical required-predicate
        # set) as ordinary internal kernel wiring -- which is precisely the
        # CAPABILITY-zone-ONLY bans: scanned as CAPABILITY it trips the kind set
        # {adapter_module_import, adapter_registry_reference,
        # sealed_kernel_import} and scans clean as SEALED_KERNEL, so this
        # membership is load-bearing, not decorative. Deliberately no violation
        # COUNT here: the count tracks how many times the module happens to name
        # a kernel symbol (an added type annotation changes it), so a number
        # recorded in a permanent comment is a code-structure measurement that
        # goes stale silently -- the KIND SET is the durable fact, and it is what
        # the pinned counterfactual asserts (proved by
        # SealedKernelZoneMembershipTests in
        # test_external_write_trial_eligibility.py, which asserts BOTH
        # directions). It is the same class as capability_invariants.py's entry
        # above, for the identical reason: a READ of the frozen dispatch record.
        # It imports no vendor SDK, constructs/obtains no write-capable
        # credential, performs no vendor mutation, writes nothing to disk, and
        # never calls run_operation -- so it passes every UNIVERSAL bypass check
        # on its own merits and needs exemption only from the four
        # CAPABILITY-zone-only rules. SEALED_KERNEL membership does NOT grant a
        # capability the right to import it (that is the independent
        # scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES set): the trial
        # protocol is kernel-driven, and capability code has no business
        # deciding its own trial eligibility.
        "trial_eligibility.py",
        # write_authorization.py: the split of AUTHORIZATION out of EXECUTION --
        # the ONE implementation of "may this write proceed" (plan once, run the
        # trial-eligibility preflight when the intent is a trial, run the
        # deterministic pre-write gate, validate the receipt) and the single
        # AuthorizedPlan carrier both the ordinary executor and a journaled trial
        # executor consume. It imports the sibling kernel `adapter_registry`
        # (`get_dispatch`), `write_gate` (the gate + the public target/cap
        # resolvers), `trial_eligibility` (the preflight) and `operations` as
        # ordinary internal kernel wiring -- which is precisely the
        # CAPABILITY-zone-ONLY bans: scanned as CAPABILITY it trips the kind set
        # {adapter_module_import, adapter_registry_reference,
        # sealed_kernel_import} and scans clean as SEALED_KERNEL, so this
        # membership is load-bearing, not decorative (both directions pinned by
        # ZoneMembershipTests in test_external_write_write_authorization.py).
        # Deliberately no violation COUNT recorded here: a count tracks how many
        # times the module happens to NAME a kernel symbol, so an added
        # annotation makes a recorded number stale silently -- the KIND SET is
        # the durable fact. It imports no vendor SDK, constructs/obtains no
        # write-capable credential (it cannot even accept one -- credential
        # isolation keeps write-client resolution inside the adapter EXECUTION
        # path), performs no vendor mutation, and writes nothing to disk itself
        # (the gate it calls consumes the blast-radius ledger, which for a
        # PERSISTENT ledger is a real write -- unchanged, and the ledger's own
        # file reached through the shared funnel, not anything this module owns).
        # SEALED_KERNEL membership does NOT grant a capability the right to
        # import it (that is the independent
        # scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES set): a capability
        # has no business authorizing its own external write.
        "write_authorization.py",
        # trial_journal.py (Cut 1.9 Task 3): the trial WRITE-AHEAD JOURNAL --
        # the durable per-unit record (`security/trial_runs/<trial_id>.json`)
        # that makes a journaled trial survivable across a crash, plus the
        # JSON-only per-unit recovery-capsule format. It imports the sibling
        # kernel `write_authorization` (the AuthorizedPlan carrier a trial is
        # opened from, and the trial intent/target constants) as ordinary
        # internal kernel wiring -- which is precisely the CAPABILITY-zone-ONLY
        # module-boundary ban: scanned as CAPABILITY it trips the kind set
        # {sealed_kernel_import} and scans clean as SEALED_KERNEL, so this
        # membership is load-bearing, not decorative (both directions pinned by
        # ZoneMembershipTests in test_external_write_trial_journal.py).
        # Deliberately no violation COUNT recorded here: a count tracks how many
        # times the module happens to NAME a kernel symbol, so an added
        # annotation makes a recorded number stale silently -- the KIND SET is
        # the durable fact.
        #
        # It DOES write to disk, unlike the two entries above -- that is the
        # entire point of the module -- but disk I/O is not one of the checks
        # scan.py enforces in any zone, and the file it writes is its own
        # gitignored record under `security/`, never a vendor mutation. It
        # imports no vendor SDK, constructs/obtains no write-capable credential
        # (it cannot even accept one), performs no vendor mutation, and never
        # calls run_operation -- so it passes every UNIVERSAL bypass check on its
        # own merits and needs exemption only from the CAPABILITY-zone-only
        # rules. Leaving it CAPABILITY (the fail-closed default) would be the
        # wrong classification for the same reason dependency_enrollment.py's
        # entry above gives: the next tightening of the CAPABILITY-zone rules
        # would make trusted kernel machinery look like an ungated capability
        # bypass.
        #
        # SEALED_KERNEL membership does NOT grant a capability the right to
        # import it (that is the independent
        # scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES set): the trial
        # protocol is kernel-driven, and capability code has no business writing
        # the record that authorizes its own external mutations.
        "trial_journal.py",
        # trial_executor.py (Cut 1.9 Task 4): the journaled TRIAL EXECUTOR -- the
        # driver that carries one authorized operation through
        # apply -> observe -> undo -> observe against the operator's live record
        # under the bounded trial target, and emits the `copy_run_proof` that
        # acceptance requires. It is the production caller of BOTH
        # `write_authorization`'s trial branch and `trial_journal`.
        #
        # This is the one entry in this set that DOES perform a vendor mutation,
        # so its membership deserves more than the usual sentence. It does not
        # weaken any UNIVERSAL bypass check: the mutation happens by calling the
        # REGISTERED ADAPTER's own captured `apply_one`/`undo_one` through the
        # frozen dispatch record -- the same chokepoint the ordinary write path
        # uses -- never by reaching a vendor SDK, which it does not import, and
        # never with a credential it constructs, since it resolves the
        # write-capable client through `adapter_registry.resolve_write_client`,
        # the shared resolver keyed by the adapter's OWN provisioner. What it
        # needs exemption from is the CAPABILITY-zone-ONLY module-boundary ban:
        # scanned as CAPABILITY it trips {adapter_module_import,
        # adapter_registry_reference, sealed_kernel_import} on its ordinary
        # internal kernel imports, and scans clean as SEALED_KERNEL. No violation
        # COUNT is recorded, for the reason trial_journal.py's entry gives: a
        # count goes stale silently, the KIND SET is the durable fact.
        #
        # SEALED_KERNEL membership emphatically does NOT grant a capability the
        # right to import it (the independent
        # scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES set governs that,
        # and this module is absent from it): a capability driving the external
        # writes it proposed is the exact inversion the whole authorization split
        # exists to prevent.
        "trial_executor.py",
    }
)

# ---------------------------------------------------------------------------
# ADAPTER_PROFILE -- registered per-vendor adapter modules. Deliberately NOT
# a directory rule: a build or test wiring that needs a DIFFERENT set (e.g.
# an isolated test fixture tree) passes its own frozenset explicitly via the
# `adapter_profile_paths` parameter of `classify_zone` / `scan_paths` /
# `run_coverage_gate` rather than mutating this module-level default.
#
# "adapters_gmail.py" (Task 7 — external-write-gate-generalization slice) is
# the first real entry: the reference Gmail verb-shaped adapter, proving the
# generalized gate against a real vendor API shape. This is the ONE-LINE,
# reviewable diff the module docstring above describes -- the file is exempt
# from every check scan.py enforces ONLY because its relative path is
# deliberately listed here, never merely because of where it lives on disk.
# ---------------------------------------------------------------------------
_BASE_ADAPTER_PROFILE_MODULE_PATHS: FrozenSet[str] = frozenset({"adapters_gmail.py"})

# ---------------------------------------------------------------------------
# Capability-added ADAPTER_PROFILE entries (Task 10 — external-write-gate-
# generalization slice; "gate-wired by construction"). A capability added
# AFTER the initial build (through the add-capability skill, long after this
# module was already installed into an operator's project) cannot practically
# hand-edit this frozenset literal the way Task 7 did for adapters_gmail.py --
# there is no human maintainer available to make that one-line diff at
# add-capability time; the operator is non-technical and the skill must land
# it BY CONSTRUCTION with zero manual wiring.
#
# So the effective ADAPTER_PROFILE allowlist is the hardcoded base set above
# UNION whatever is declared in a sibling, deliberately-reviewable JSON file:
# <this module's own directory>/adapter_profile_registry.json -- a plain JSON
# array of relative filenames. wizard/scripts/lib/capability_code_scaffold.py
# (the deterministic emitter add-capability's build cascade invokes for a
# writes-back capability) appends the new adapter module's filename there
# when it emits it; it never edits THIS file's source. This is still the same
# "explicit, reviewable, one-line diff" shape the module docstring above
# describes -- a git diff of the registry file shows exactly the one line
# added -- it is simply written by the deterministic emitter instead of by
# hand.
#
# Fail-closed: a missing, unreadable, malformed, non-list, or non-string-
# entry registry file resolves to NO additional paths (never an exception,
# never a silent grant of something unintended) -- the same disclosed-bound
# spirit as every other fail-closed default in this package. A file that is
# not listed here (and not in SEALED_KERNEL_MODULE_PATHS) is CAPABILITY, the
# most restrictive zone, exactly as before.
# ---------------------------------------------------------------------------
_ADAPTER_PROFILE_REGISTRY_FILENAME = "adapter_profile_registry.json"


def _load_extra_adapter_profile_paths(lib_dir: Path) -> FrozenSet[str]:
    """Fail-closed loader for capability-added ADAPTER_PROFILE entries.

    Reads ``<lib_dir>/adapter_profile_registry.json`` -- a plain JSON array of
    relative filenames. Returns an empty frozenset (never raises) when the
    file is absent, unreadable, not valid JSON, not a JSON array, or contains
    a non-string / empty entry (that one entry is simply skipped, not fatal
    to the rest -- fail-closed per-entry, not fail-open on the whole file).
    """
    registry_path = Path(lib_dir) / _ADAPTER_PROFILE_REGISTRY_FILENAME
    if not registry_path.is_file():
        return frozenset()
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return frozenset()
    if not isinstance(data, list):
        return frozenset()
    return frozenset(p for p in data if isinstance(p, str) and p)


def effective_adapter_profile_paths(lib_dir: Optional[Path] = None) -> FrozenSet[str]:
    """The full ADAPTER_PROFILE allowlist for the ``external_write`` package
    rooted at `lib_dir`: the hardcoded base set (``adapters_gmail.py``) UNION
    any capability-added entries declared in
    ``<lib_dir>/adapter_profile_registry.json`` (see the module-level
    docstring block above this function for the full rationale).

    `lib_dir` defaults to THIS module's own installed directory (the real
    package anchor -- mirrors ``scan.py``'s ``_default_kernel_anchor``) when
    omitted, so production callers that read the ``ADAPTER_PROFILE_MODULE_PATHS``
    module constant below (computed by calling this function with no
    argument, once, at import time) get the fully merged set with zero code
    changes -- a capability the emitter adds after this module was first
    imported in a given process is picked up on the process's next start,
    the same "read once, not per-call" cadence this module already had.

    A caller building/testing against an arbitrary directory (e.g. a golden-
    emit test writing into a temporary project) passes its own `lib_dir`
    explicitly instead of relying on the process-wide default.
    """
    anchor = Path(lib_dir) if lib_dir is not None else Path(__file__).resolve().parent
    return _BASE_ADAPTER_PROFILE_MODULE_PATHS | _load_extra_adapter_profile_paths(anchor)


ADAPTER_PROFILE_MODULE_PATHS: FrozenSet[str] = effective_adapter_profile_paths()


def _resolve_relative(file_path: Path, anchor: Path) -> Union[str, None]:
    """Return file_path's POSIX path relative to anchor, or None if file_path
    does not resolve to a location under anchor at all."""
    resolved = file_path.resolve()
    try:
        is_under = resolved.is_relative_to(anchor)
    except AttributeError:  # pragma: no cover - py<3.9 fallback
        try:
            resolved.relative_to(anchor)
            is_under = True
        except ValueError:
            is_under = False
    if not is_under:
        return None
    return resolved.relative_to(anchor).as_posix()


def classify_zone(
    file_path: Union[str, Path],
    kernel_anchor: Path,
    *,
    sealed_kernel_paths: FrozenSet[str] = SEALED_KERNEL_MODULE_PATHS,
    adapter_profile_paths: FrozenSet[str] = ADAPTER_PROFILE_MODULE_PATHS,
) -> Zone:
    """Classify ``file_path`` into one of the three trust zones.

    Fail-closed (acceptance criterion: "unknown/unclassifiable module =>
    fail-closed, treated as capability"): a file that is not explicitly
    listed in ``sealed_kernel_paths`` or ``adapter_profile_paths`` is
    CAPABILITY -- the most restrictive zone -- regardless of whether it
    physically lives under ``kernel_anchor``. Physical location under the
    anchor is NECESSARY but never SUFFICIENT for SEALED_KERNEL or
    ADAPTER_PROFILE membership; the relative path must also be explicitly
    enumerated. This is what stops a new file (or a whole new adapter
    directory) from being silently exempted the moment it is created under
    the package -- see module docstring.
    """
    rel = _resolve_relative(Path(file_path), kernel_anchor)
    if rel is None:
        return Zone.CAPABILITY
    if rel in sealed_kernel_paths:
        return Zone.SEALED_KERNEL
    if rel in adapter_profile_paths:
        return Zone.ADAPTER_PROFILE
    return Zone.CAPABILITY
