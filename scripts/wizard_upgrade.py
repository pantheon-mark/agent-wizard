#!/usr/bin/env python3
"""Wizard upgrade CLI.

Argparse-only shim; engine lives in `wizard/scripts/lib/upgrade.py` (library-first split).

Subcommands (per the foundation-versioning policy upgrade flow):
    upgrade-check          Inspect operator-project drift + available targets
    upgrade                Plan-only by default; --apply performs the merge-apply
    upgrade-plan           Synonym for `upgrade --plan-only`

Usage:
    wizard_upgrade.py upgrade-check [--manifest-path PATH] [--registry-path PATH] [--json]
    wizard_upgrade.py upgrade --to VERSION --plan-only [--manifest-path PATH] [--registry-path PATH] [--json]
    wizard_upgrade.py upgrade --to VERSION --apply [--ack] [--manifest-path PATH] [--registry-path PATH]
    wizard_upgrade.py upgrade-plan --to VERSION [--manifest-path PATH] [--registry-path PATH] [--json]

Exit codes:
    0  success (plan emitted; or apply completed cleanly)
    1  upgrade engine error (manifest / registry / target version / drift-class; or apply refused)
    2  tooling error (invalid CLI arguments; neither --plan-only nor --apply given)

The apply path (`--apply`) changes ONLY the foundation documents the target bundle
carries, gated on explicit operator action. There is no --latest; the operator
names the target version. Standing auto-approval is fully disabled — every apply is
operator-explicit.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# The apply engine (upgrade_apply) uses sibling imports (generator / upgrade /
# replay_capsule), so lib/ must be importable as a flat directory too.
_LIB = _HERE / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from lib.upgrade import (  # noqa: E402
    BundleNotFoundError,
    MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME,
    OPERATOR_MANIFEST_JSON_FILENAME,
    OperatorManifestError,
    PlanOnlyRequiredError,
    RegistryError,
    UpdateCheckOutcome,
    UpdateStatus,
    UpgradeError,
    classify_update_status,
    check_engine_compatibility,
    compute_recommendation,
    compute_upgrade_analysis,
    compute_upgrade_check,
    compute_upgrade_plan,
    find_bundle_entry,
    load_migration_manifest,
    load_operator_manifest,
    load_registry,
    render_update_status,
    render_upgrade_check,
    render_upgrade_plan,
    resolve_bundle_dir,
    resolve_toolkit_root,
    status_exit_code,
    update_outcome_to_dict,
    upgrade_check_to_dict,
    upgrade_plan_to_dict,
)
from lib.upgrade_apply import (  # noqa: E402
    apply_upgrade,
    compute_target_change_set,
    render_apply_result,
    UpgradeApplyError,
)
from lib.self_update import (  # noqa: E402
    apply_self_update,
    render_self_update_result,
    self_update_exit_code,
    verify_self_update,
)
from lib.update_source import record_last_known_good_commit  # noqa: E402
from lib.registry_fetch import fetch_remote_registry  # noqa: E402
from lib.resolution_emit import (  # noqa: E402
    compute_update_resolution_for_target,
    emit_update_resolution_for_target,
)
from lib.update_resolution import (  # noqa: E402
    UpdateResolutionError,
    load_update_resolution,
    write_update_resolution,
)
from lib.run_upgrade import run_resolution_upgrade  # noqa: E402


def populate_plan_analysis(
    plan,
    operator_dir: Path,
    target_version: str,
    build_repo_root: Path,
    registry: dict,
    manifest: dict,
    registry_path: Path,
) -> None:
    """Populate `plan.artifact_analysis` over the TARGET-CHANGE SET (read-only).

    This is the wiring the prior C1 build was missing: it computes the artifacts the
    target version adds/modifies (reusing the apply engine's render + surface
    computation, read-only via `compute_target_change_set`), loads the target
    migration-manifest's `artifact_notes` for the plain-language benefit text, and
    joins them into per-artifact analysis entries on the plan.

    Fail-soft: any error here (e.g. a legacy v1 capsule that cannot replay the
    operating layer, or a missing migration manifest) leaves `artifact_analysis = []`
    and the plan still renders — the drift report remains the complementary
    "your local changes" view. For a v2-capsule system this populates the full set."""
    try:
        change_set = compute_target_change_set(
            operator_dir, target_version, build_repo_root,
            registry=registry, manifest=manifest,
        )
    except UpgradeError:
        return
    if not change_set:
        return
    migration_manifest: dict = {}
    target_entry = find_bundle_entry(registry, target_version)
    if target_entry is not None:
        # Registry-relative, layout-agnostic (build-repo + public-clone). Was a fixed
        # `build_repo_root / entry["path"]` join that re-prepended the build-repo
        # `wizard/` prefix and broke in the prefix-stripped public clone (F-OR-4).
        migration_json = (
            resolve_bundle_dir(registry_path, registry, target_entry)
            / MIGRATION_MANIFEST_JSON_SIDECAR_FILENAME
        )
        if migration_json.exists():
            try:
                migration_manifest = load_migration_manifest(migration_json)
            except UpgradeError:
                migration_manifest = {}
    plan.artifact_analysis = compute_upgrade_analysis(change_set, migration_manifest)


def _resolve_build_repo_root(registry_path: Path) -> Path:
    """Resolve the toolkit root the apply/render path resolves bundles under.

    Registry-relative + layout-agnostic (operator-reach C1', fixes F-OR-4): the
    registry ALWAYS lives at `<toolkit>/registry/foundation-bundles.json`, so the
    toolkit root is the registry file's grandparent in BOTH shipping layouts:

      * BUILD-REPO  : `<root>/wizard/registry/...` -> `<root>/wizard`
      * PUBLIC-CLONE: `<clone>/registry/...`       -> `<clone>` (the `git subtree
        --prefix=wizard` split strips the `wizard/` prefix)

    The render engine (`bundle_templates.wizard_subroot`) accepts this toolkit root
    directly: it detects that the value already contains `foundation-bundles/` and does
    not re-prepend a `wizard/` segment, so resolution is identical in both layouts. The
    canonical per-bundle directory resolution is registry-relative
    (`upgrade.resolve_bundle_dir`).

    Was `registry_path.resolve().parent.parent.parent`, which assumed the build-repo
    `wizard/` prefix and re-prepended it in the prefix-stripped public clone -> the
    public clone was un-runnable (registry-not-found / bundle-directory-missing)."""
    return resolve_toolkit_root(registry_path)


_DEFAULT_REGISTRY_PATH = Path("wizard/registry/foundation-bundles.json")
_DEFAULT_MANIFEST_RELATIVE = Path(".wizard") / OPERATOR_MANIFEST_JSON_FILENAME


def _resolve_manifest_path(manifest_arg: str | None) -> Path:
    """Resolve --manifest-path; default = ./.wizard/manifest.json relative to cwd."""
    if manifest_arg:
        return Path(manifest_arg)
    return Path.cwd() / _DEFAULT_MANIFEST_RELATIVE


def _resolve_registry_path(registry_arg: str | None) -> Path:
    """Resolve --registry-path. Default = the TOOLKIT's own registry, resolved relative
    to THIS engine file (`<toolkit>/scripts/wizard_upgrade.py` -> `<toolkit>/registry/
    foundation-bundles.json`), NOT cwd-relative. This lets an operator run `wizard ...`
    from their OWN project directory and still find the toolkit's version list — the bug
    a cwd-relative default caused (the operator's project has no `registry/`). Works in
    both layouts: build-repo `<root>/wizard/...` and public clone `<clone>/...` (the
    `scripts/` + `registry/` siblings sit directly under the toolkit root in each). The
    manifest path deliberately STAYS cwd-relative: that IS the operator's project."""
    if registry_arg:
        return Path(registry_arg)
    toolkit_root = Path(__file__).resolve().parent.parent
    return toolkit_root / "registry" / "foundation-bundles.json"


def _emit_outcome(outcome, args, *, detail_render: str = "") -> int:
    """Shared emit for the typed honest-status contract: --json emits the structured
    outcome (status / reason_code / fields); otherwise the operator-facing message
    (rendered ONLY from the typed status, never raw logs) plus optional detail. Returns
    the status-mapped exit code so the could-not-determine band never collapses to 0."""
    if args.json:
        print(json.dumps(update_outcome_to_dict(outcome), sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_update_status(outcome))
        if detail_render:
            print()
            print(detail_render, end="")
    return status_exit_code(outcome.status)


def _try_load_local_registry(registry_path: Path) -> dict | None:
    """The local toolkit registry mirror, or None if absent/unreadable. The mirror is NOT
    the currency authority (that is the remote source); it is consulted only to (a) decide
    NETWORK_UNAVAILABLE vs CURRENCY_UNCONFIRMED on a remote-fetch failure, and (b) run the
    engine-compatibility gate when the target bundle is actually present locally."""
    try:
        registry = load_registry(registry_path)
        return registry if registry.get("bundles") else None
    except (RegistryError, UpgradeError):
        return None


def _classify_local_miss(operator_dir: Path, target: str) -> int:
    """Secondary safety net for MANUAL CLI use: when `upgrade-plan`/`upgrade --to V`
    misses in the LOCAL toolkit registry, do NOT emit a bare 'not in registry' (which the
    assistant read as 'no notes/prerelease -> hold off'). Time-boxed remote fetch distinguishes:
      - TOOLKIT_BEHIND   : remote HAS V, local lacks it -> route to `self-upgrade` (refresh+apply)
      - VERSION_NOT_FOUND: remote lacks V too -> honest 'not a published version'
      - CURRENCY_UNCONFIRMED: remote unreachable/unverifiable -> never claim 'not found'
    The bundle FILES live in the toolkit clone, so a behind toolkit genuinely cannot apply V
    until refreshed; `self-upgrade --to V --apply` does the refresh+apply and re-verifies first.
    Preview stays distinct from apply (never present --apply as the only route from a preview)."""
    # short timeout: this is a fallback classifier, must not hang a local command.
    fetch = fetch_remote_registry(operator_dir, timeout=5)
    if fetch.ok and find_bundle_entry(fetch.registry, target) is not None:
        print(
            f"TOOLKIT_BEHIND: version {target} is published, but your local update tool is "
            f"behind and does not carry it yet.\n"
            f"  To apply it:    wizard self-upgrade --to {target} --apply\n"
            f"                  (refreshes the tool to {target}, then applies — it re-verifies "
            f"against the official source before changing anything).\n"
            f"  To preview first: refresh the tool, then run  wizard upgrade-plan --to {target}",
            file=sys.stderr,
        )
        return 1
    if fetch.ok:
        print(
            f"VERSION_NOT_FOUND: {target} is not a published version (it is not in the official "
            f"registry). Check the version, or run `wizard upgrade-check` to see what is available.",
            file=sys.stderr,
        )
        return 1
    fstat = fetch.failure_status.value if fetch.failure_status else "unreachable"
    print(
        f"CURRENCY_UNCONFIRMED: can't confirm {target} against the official update source right "
        f"now ({fstat}). This is NOT a confirmation that the version doesn't exist. If an update "
        f"notice showed it, your tool may simply be behind — run `wizard self-upgrade --to {target} "
        f"--apply` when you're back online (it re-verifies before changing anything).",
        file=sys.stderr,
    )
    return 1


def cmd_upgrade_check(args: argparse.Namespace) -> int:
    """`wizard upgrade-check` — typed honest-status contract, REMOTE-AUTHORITATIVE.

    Version availability is decided against the AUTHORITATIVE remote registry (fetched as
    DATA from the origin-pinned update source via the shared `fetch_remote_registry` routine —
    the same routine the SessionStart notice uses, so the two can never disagree). The check
    fails CLOSED: if the remote cannot be reached/verified it reports a could-not-determine
    status and NEVER `CHECKED_CURRENT` off a stale local mirror. The local mirror is demoted
    to a fallback signal only (network-unreachable-but-local-exists -> CURRENCY_UNCONFIRMED)
    and to the engine-compat gate when the target bundle is locally present."""
    manifest_path = _resolve_manifest_path(args.manifest_path)
    registry_path = _resolve_registry_path(args.registry_path)

    # Operator-manifest load failures are an operator/config error, not an
    # update-status determination — keep the legacy tooling exit code 1.
    try:
        manifest = load_operator_manifest(manifest_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    operator_dir = manifest_path.parent.parent
    current_version = manifest.get("foundation_bundle_version", "")

    # AUTHORITATIVE: fetch the remote registry. Fail CLOSED on any fetch/verify failure.
    fetch = fetch_remote_registry(operator_dir)
    if not fetch.ok:
        # Normalize by VALUE: registry_fetch resolves `upgrade` as a flat module while this
        # CLI resolves it as `lib.upgrade`, so the two UpdateStatus enums are not identity-
        # equal across the dual import paths. Rebuild the member in THIS module's enum so the
        # comparison + construction + render below all use one identity.
        raw_status = fetch.failure_status or UpdateStatus.COULD_NOT_CHECK
        status = UpdateStatus(raw_status.value)
        # A reachable-but-stale local mirror does not make us current: if the remote was
        # simply unreachable AND a local catalog exists, the honest status is
        # CURRENCY_UNCONFIRMED (local data exists, authority not reached) — not bare network.
        if status == UpdateStatus.NETWORK_UNAVAILABLE and _try_load_local_registry(registry_path) is not None:
            status = UpdateStatus.CURRENCY_UNCONFIRMED
        return _emit_outcome(
            UpdateCheckOutcome(
                status=status,
                reason_code=f"remote_registry_unavailable_{status.value}",
                current_version=current_version,
                detail=fetch.detail,
            ),
            args,
        )

    registry = fetch.registry  # the authoritative remote registry

    # registry_path=None: availability is decided from the remote version list ALONE — do NOT
    # read per-target migration manifests from local disk (the newer target is not local yet;
    # a local read would fail-closed on exactly the available-update case). Migration detail +
    # engine-compat enrichment happen at plan/apply time after the toolkit refresh.
    try:
        result = compute_upgrade_check(operator_dir, manifest, registry, registry_path=None)
    except (RegistryError, UpgradeError) as e:
        return _emit_outcome(classify_update_status(e), args)

    # Engine-compatibility gate (MF-2): only determinable when the latest available target's
    # bundle is present in the LOCAL toolkit (older targets may be; the just-published latest
    # usually is not until a refresh). When it is not local, availability stands honestly and
    # the engine-compat STOP is re-checked at apply (after self-update fetches the bundle).
    engine_too_old = False
    min_engine = ""
    if result.available_targets:
        latest_target = result.available_targets[-1].get("foundation_bundle_version", "")
        local_registry = _try_load_local_registry(registry_path)
        local_entry = find_bundle_entry(local_registry, latest_target) if local_registry else None
        if local_entry is not None:
            try:
                compat = check_engine_compatibility(registry_path, local_registry, local_entry)
                if not compat.compatible:
                    engine_too_old = True
                    min_engine = compat.min_engine_version
            except (RegistryError, UpgradeError):
                pass  # cannot determine locally -> do not gate; availability stands

    outcome = classify_update_status(
        result, engine_too_old=engine_too_old, min_engine_version=min_engine,
    )
    detail = "" if args.json else render_upgrade_check(result)
    return _emit_outcome(outcome, args, detail_render=detail)


def _run_upgrade_plan(args: argparse.Namespace, plan_only_invoked_via_synonym: bool) -> int:
    """Shared body for `upgrade --plan-only` + `upgrade-plan` synonym."""
    manifest_path = _resolve_manifest_path(args.manifest_path)
    registry_path = _resolve_registry_path(args.registry_path)
    try:
        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    operator_dir = manifest_path.parent.parent
    try:
        plan = compute_upgrade_plan(operator_dir, manifest, args.to, registry, registry_path=registry_path)
    except BundleNotFoundError:
        # F-10: local-registry miss -> classify (toolkit-behind / not-found / unconfirmed) and
        # route to self-upgrade instead of a bare 'not in registry'.
        return _classify_local_miss(operator_dir, args.to)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    # Populate the per-artifact analysis over the target-change set (read-only). This is
    # the wiring the prior C1 build omitted, which left artifact_analysis empty on every
    # real plan run. Fail-soft: leaves the analysis empty if it cannot be computed.
    populate_plan_analysis(
        plan, operator_dir, args.to,
        _resolve_build_repo_root(registry_path), registry, manifest,
        registry_path=registry_path,
    )
    if args.json:
        print(json.dumps(upgrade_plan_to_dict(plan), sort_keys=True, indent=2, ensure_ascii=False))
    else:
        print(render_upgrade_plan(plan), end="")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    """`wizard upgrade --to VERSION --apply [--ack]` — the merge-apply path.

    Changes ONLY the foundation documents the target bundle carries. Operator-edited
    files are never clobbered: they are kept in place and the new version is saved
    for review. Every apply is operator-explicit (no standing auto-approval)."""
    manifest_path = _resolve_manifest_path(args.manifest_path)
    registry_path = _resolve_registry_path(args.registry_path)
    try:
        manifest = load_operator_manifest(manifest_path)
        registry = load_registry(registry_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    operator_dir = manifest_path.parent.parent
    build_repo_root = _resolve_build_repo_root(registry_path)
    try:
        result = apply_upgrade(
            operator_dir, args.to, build_repo_root,
            registry=registry, registry_path=registry_path,
            manifest=manifest, manifest_path=manifest_path,
            ack=args.ack,
        )
    except BundleNotFoundError:
        # F-10: stale-toolkit apply of a remote-only version -> route to self-upgrade, not a bare
        # 'not in registry'. (BundleNotFoundError subclasses UpgradeError, so catch it first.)
        return _classify_local_miss(operator_dir, args.to)
    except UpgradeApplyError as e:
        # Refusal — no live writes. Surface the actionable message verbatim.
        print(f"upgrade refused: {e}", file=sys.stderr)
        return 1
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(render_apply_result(result), end="")
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    """`wizard upgrade --to VERSION` — plan-only by default; `--apply` mutates.

    Exactly one of `--plan-only` / `--apply` must be given (`--apply` performs the
    merge-apply; `--plan-only` previews without changing anything)."""
    if args.apply and args.plan_only:
        print("error: pass only one of --plan-only / --apply, not both.", file=sys.stderr)
        return 2
    if args.apply:
        return cmd_apply(args)
    if args.plan_only:
        return _run_upgrade_plan(args, plan_only_invoked_via_synonym=False)
    msg = (
        "error: `wizard upgrade --to <version>` requires --plan-only (preview) or --apply (apply).\n"
        "       --plan-only shows what would change without touching files.\n"
        "       --apply performs the foundation-document upgrade (operator-explicit; add --ack to\n"
        "       adopt the new version of any file you have edited under a warn-on-drift rule)."
    )
    print(msg, file=sys.stderr)
    return 2


def cmd_upgrade_plan(args: argparse.Namespace) -> int:
    """`wizard upgrade-plan --to VERSION` (synonym for `upgrade --to VERSION --plan-only`)."""
    return _run_upgrade_plan(args, plan_only_invoked_via_synonym=True)


def _resolve_toolkit_dir(toolkit_arg: str | None) -> Path:
    """Resolve the installed-toolkit directory. Default = this engine's own toolkit root
    (`scripts/`'s parent), i.e. the directory the running engine lives under. This is the
    directory the guarded self-update verifies + backs up + swaps."""
    if toolkit_arg:
        return Path(toolkit_arg)
    return _HERE.parent


def cmd_self_update(args: argparse.Namespace) -> int:
    """`wizard self-update [--check | --apply]` — the GUARDED toolkit-currency contract.

    SAFE ORDERING: the CURRENTLY-INSTALLED engine performs verify (+ backup + swap on
    --apply); the freshly-fetched code is NOT executed in this run — it runs on the
    operator's NEXT invocation. Touches ONLY the toolkit directory, never operator files.

    --check  : verify only (origin + lineage + clean tree); report; change nothing.
    --apply  : verify, back up the toolkit, swap to the verified candidate, record the
               new last-known-good commit. Fail-closed on any failed gate.
    """
    toolkit_dir = _resolve_toolkit_dir(args.toolkit_dir)
    # The operator project is where `.wizard/update-source.json` lives (the pinned source).
    operator_dir = (
        Path(args.operator_dir) if args.operator_dir else _resolve_manifest_path(None).parent.parent
    )
    candidate = args.to_commit or None

    if args.apply:
        result = apply_self_update(
            toolkit_dir, operator_dir, candidate_commit=candidate,
            record_commit_fn=lambda c: record_last_known_good_commit(operator_dir, c),
        )
    else:
        # Default + --check: verify only, never mutate.
        result = verify_self_update(toolkit_dir, operator_dir, candidate_commit=candidate)

    print(render_self_update_result(result, json_mode=args.json), end="")
    # Reuse the typed status -> exit-code mapping so a caller branches on the outcome.
    # Routed through the engine's own helper to avoid an enum-identity mismatch across
    # module import paths.
    return self_update_exit_code(result)


def _commit_matches(full: str, expect: str) -> bool:
    """True if `full` (the live-resolved 40-hex commit) matches the operator's previewed `expect`
    token. Accepts a prefix (>= 7 hex) so the apply command we render can carry a 12-char commit and
    stay wrap-safe. Empty `expect` means 'no expectation given' (the caller decides what to do)."""
    full = (full or "").strip().lower()
    expect = (expect or "").strip().lower()
    if not expect:
        return True
    if len(expect) < 7:
        return False
    return full == expect or full.startswith(expect)


def _stale_preview_msg(target_version: str) -> str:
    return (
        "error: the update you previewed is no longer what the official source now points to — it "
        "moved since you previewed it, so NOTHING was changed. Re-run the preview to see the current "
        f"change, then approve again:\n  wizard self-upgrade --to {target_version} --plan-only"
    )


def run_self_upgrade(
    *,
    operator_dir: Path,
    toolkit_dir: Path,
    registry_path: Path,
    manifest_path: Path,
    manifest: dict,
    target_version: str,
    checked_at: str,
    expect_commit: str = "",
    fetch_remote: str = "origin",
    ack: bool = True,
    backup: bool = True,
    commit_resolver=None,
    fetcher=None,
    exec_fn=None,
    apply_fn=None,
    reexec_argv=None,
    json_mode: bool = False,
) -> int:
    """The operator-reach two-phase A+ upgrade (the heart of `wizard self-upgrade`).

    PHASE 1 (first invocation): if no approved resolution exists for `target_version`, EMIT it —
    the approve step: resolve the exact public commit (real git ls-remote) + fetch the registry AT
    that commit + bind the expected bundle hashes into the immutable `.wizard/update-resolution.json`.
    Then `run_resolution_upgrade` self-updates the toolkit to that exact commit and re-execs the SAME
    command. PHASE 2 (the re-exec'd, freshly-installed engine): a matching resolution is already
    present, so emit is SKIPPED (no second git touch, no second approve) and `run_resolution_upgrade`
    re-validates the content gate and applies — performed by the NEW engine, never the old bytecode.

    Returns a process exit code (0 applied / re-exec'd; nonzero = not applied). The seams
    (commit_resolver / fetcher / exec_fn / apply_fn / reexec_argv) are injectable CODE seams (not
    env vars, so production cannot be redirected away from the origin pin) for offline tests;
    production binds the real defaults via `cmd_self_upgrade`."""
    operator_dir = Path(operator_dir)
    toolkit_dir = Path(toolkit_dir)
    registry_path = Path(registry_path)
    manifest_path = Path(manifest_path)
    current_version = manifest.get("foundation_bundle_version", "")

    # 1. EMIT-OR-SKIP. Phase 2 (re-exec'd) finds a matching resolution and must NOT re-emit (no
    #    second git touch, no second approve); phase 1 / a stale-target leftover emits afresh.
    need_emit = True
    try:
        existing = load_update_resolution(operator_dir)
        if existing.target_version == target_version:
            need_emit = False
    except UpdateResolutionError:
        need_emit = True

    if need_emit:
        emit_kwargs: dict = {}
        if commit_resolver is not None:
            emit_kwargs["commit_resolver"] = commit_resolver
        if fetcher is not None:
            emit_kwargs["fetcher"] = fetcher
        # COMPUTE the resolution first (read-only) so an --expect-commit approval guard is enforced
        # BEFORE any write or self-update: if the live-resolved commit is not the one the operator
        # previewed, fail closed having written + changed NOTHING (approve-A-apply-B is impossible).
        plan = compute_update_resolution_for_target(
            operator_dir, toolkit_dir, target_version,
            from_version=current_version, checked_at=checked_at,
            **emit_kwargs,
        )
        if plan is None:
            # Fail-closed: no pin / git could not resolve the commit / registry unfetchable at that
            # commit / target absent / registry declares no bundle hashes. Nothing was written;
            # report honestly (NEVER a false "applied" / "current"). The skill surfaces this to the
            # operator as could-not-prepare; the status of their system is unchanged.
            print(
                "error: could not prepare an approved update for "
                f"{target_version}. The update could not be verified against the official source "
                "right now, so NOTHING was changed. This is not a confirmation that you are up to "
                "date. Try again later, or refresh the tool first (`wizard self-update --apply`).",
                file=sys.stderr,
            )
            return 1
        if not _commit_matches(plan.resolution.target_public_commit_sha, expect_commit):
            print(_stale_preview_msg(target_version), file=sys.stderr)
            return 1
        write_update_resolution(operator_dir, plan.resolution)
    elif expect_commit:
        # Phase 2 / a pre-existing matching resolution: re-verify it is still the previewed commit
        # before applying (defense in depth — phase 1 already enforced this).
        try:
            existing = load_update_resolution(operator_dir)
        except UpdateResolutionError:
            existing = None
        if existing is None or not _commit_matches(existing.target_public_commit_sha, expect_commit):
            print(_stale_preview_msg(target_version), file=sys.stderr)
            return 1

    # 2. apply_fn — executed by the (re-exec'd) NEW engine in phase 2. Loads the registry lazily so
    #    a phase-1 process (which never calls apply_fn) does not depend on it, and so phase 2 reads
    #    the freshly-checked-out toolkit's registry.
    if apply_fn is None:
        def apply_fn(resolution):  # noqa: ANN001
            build_repo_root = _resolve_build_repo_root(registry_path)
            registry = load_registry(registry_path)
            try:
                result = apply_upgrade(
                    operator_dir, resolution.target_version, build_repo_root,
                    registry=registry, registry_path=registry_path,
                    manifest=manifest, manifest_path=manifest_path,
                    ack=ack, backup=backup,
                )
            except UpgradeApplyError as e:
                # Clean refusal (no live writes). Surface the actionable message verbatim.
                print(f"upgrade refused: {e}", file=sys.stderr)
                return ("apply_complete", 1)
            except UpgradeError as e:
                print(f"error: {e}", file=sys.stderr)
                return ("apply_complete", 1)
            print(render_apply_result(result), end="")
            return ("apply_complete", 0)

    run_kwargs: dict = {"argv": list(reexec_argv) if reexec_argv is not None else [],
                        "apply_fn": apply_fn, "fetch_remote": fetch_remote}
    if exec_fn is not None:
        run_kwargs["exec_fn"] = exec_fn
    out = run_resolution_upgrade(operator_dir, toolkit_dir, **run_kwargs)

    # 3. Map the orchestration result to an exit code.
    tag = out[0] if isinstance(out, tuple) and out else None
    if tag == "refused":
        # run_resolution_upgrade's own fail-closed (no resolution / content gate failed at apply).
        print(f"upgrade refused: {out[1]}", file=sys.stderr)
        return 1
    if tag == "execed":
        # Only reachable when exec_fn is a test stub; in production os.execv replaced the process.
        return 0
    if tag == "apply_complete":
        return int(out[1])
    print(f"error: unexpected upgrade result: {out!r}", file=sys.stderr)
    return 1


def render_self_upgrade_plan(plan, *, current_version: str) -> str:
    """Operator-facing preview of what `self-upgrade --to V --apply` would change, rendered from
    the computed (commit-pinned) ResolutionPlan. Carries an `--expect-commit` token (a short commit
    prefix) so the operator can apply EXACTLY what was previewed. Renders the recommendation stance
    via the same pure `compute_recommendation` the check uses (never keyed on prerelease)."""
    res = plan.resolution
    entry = plan.entry
    rec = compute_recommendation(entry)
    target = res.target_version
    short = (res.target_public_commit_sha or "")[:12]
    changelog = (entry.get("changelog") or rec.get("recommendation_reason") or "").strip() \
        or "(no description published yet)"
    reason = rec.get("recommendation_reason", "").strip()
    lines = [
        f"Update preview — {current_version or '(current)'} -> {target}",
        f"  What's new:      {changelog}",
        f"  Recommendation:  {rec['recommendation_stance']}"
        + (f" — {reason}" if reason else ""),
        f"  Safety class:    {rec['safety_class']}",
        f"  Pinned to:       commit {short}",
        "  This preview changed NOTHING (no files touched, tool not refreshed).",
        "",
        "  To apply exactly what you previewed:",
        f"      wizard self-upgrade --to {target} --apply --expect-commit {short}",
        "",
    ]
    return "\n".join(lines)


def run_self_upgrade_plan(
    *,
    operator_dir: Path,
    toolkit_dir: Path,
    target_version: str,
    from_version: str,
    checked_at: str,
    commit_resolver=None,
    fetcher=None,
    json_mode: bool = False,
) -> int:
    """`wizard self-upgrade --to V --plan-only` — a strictly READ-ONLY preview of what applying
    would change. Resolves the target's exact public commit + fetches the registry AT that commit
    + renders the preview, and writes NOTHING (no `.wizard/update-resolution.json`, no toolkit
    refresh, no apply). Honest fail: if the official source can't be reached/verified, report
    could-not-confirm — never a stale or fabricated preview."""
    operator_dir = Path(operator_dir)
    toolkit_dir = Path(toolkit_dir)
    kwargs: dict = {}
    if commit_resolver is not None:
        kwargs["commit_resolver"] = commit_resolver
    if fetcher is not None:
        kwargs["fetcher"] = fetcher
    plan = compute_update_resolution_for_target(
        operator_dir, toolkit_dir, target_version,
        from_version=from_version, checked_at=checked_at,
        **kwargs,
    )
    if plan is None:
        print(
            f"CURRENCY_UNCONFIRMED: couldn't confirm {target_version} against the official update "
            "source right now, so there is nothing to preview. This is NOT a confirmation that you "
            "are up to date — try again when you're back online.",
            file=sys.stderr,
        )
        return 1
    if json_mode:
        rec = compute_recommendation(plan.entry)
        print(json.dumps({
            "status": "plan_only",
            "from_version": from_version,
            "target_version": plan.resolution.target_version,
            "expected_commit": plan.resolution.target_public_commit_sha,
            "changelog": plan.entry.get("changelog", ""),
            "recommendation": rec,
            "wrote_anything": False,
        }, indent=2))
    else:
        print(render_self_upgrade_plan(plan, current_version=from_version), end="")
    return 0


def cmd_self_upgrade(args: argparse.Namespace) -> int:
    """`wizard self-upgrade --to VERSION --apply` — the operator-reach combined upgrade.

    Refreshes the installed toolkit to the EXACT approved public commit, then re-runs itself and
    applies the foundation/operating-layer update with the freshly-installed engine. One operator
    "yes" (handled by the check-for-updates skill) drives the whole chain; this command is
    non-interactive so it survives the os.execv re-run with no human in the loop.

    Operator-edited warn-on-drift files are adopted to the new version with a backup taken first
    (ack=True); the operator's own data, rules, credentials, and logs (`operator_review`) are never
    touched. Every run is operator-explicit — standing auto-approval stays disabled."""
    plan_only = getattr(args, "plan_only", False)
    if args.apply and plan_only:
        print("error: pass only one of --plan-only / --apply, not both.", file=sys.stderr)
        return 2
    if not args.apply and not plan_only:
        print(
            "error: `wizard self-upgrade --to <version>` requires --plan-only (preview) or --apply.\n"
            "       --plan-only shows what would change without touching anything; --apply refreshes\n"
            "       the tool to the approved version and applies the update in one step.",
            file=sys.stderr,
        )
        return 2

    manifest_path = _resolve_manifest_path(args.manifest_path)
    registry_path = _resolve_registry_path(args.registry_path)
    toolkit_dir = _resolve_toolkit_dir(args.toolkit_dir)
    try:
        manifest = load_operator_manifest(manifest_path)
    except UpgradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    operator_dir = Path(args.operator_dir) if args.operator_dir else manifest_path.parent.parent
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    current_version = manifest.get("foundation_bundle_version", "")

    if plan_only:
        # Strictly read-only preview — writes nothing, refreshes nothing, applies nothing.
        return run_self_upgrade_plan(
            operator_dir=operator_dir,
            toolkit_dir=toolkit_dir,
            target_version=args.to,
            from_version=current_version,
            checked_at=checked_at,
            json_mode=args.json,
        )

    fetch_remote = args.fetch_remote or "origin"
    return run_self_upgrade(
        operator_dir=operator_dir,
        toolkit_dir=toolkit_dir,
        registry_path=registry_path,
        manifest_path=manifest_path,
        manifest=manifest,
        target_version=args.to,
        checked_at=checked_at,
        expect_commit=getattr(args, "expect_commit", None) or "",
        fetch_remote=fetch_remote,
        json_mode=args.json,
        reexec_argv=list(sys.argv),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wizard_upgrade",
        description=(
            "Foundation-bundle upgrade CLI (plan-only preview + operator-explicit apply). "
            "Per the foundation-versioning policy upgrade flow."
        ),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    check_p = sub.add_parser("upgrade-check", help="Inspect operator-project drift + available targets")
    check_p.add_argument("--manifest-path", default=None,
                         help="Path to operator-project `.wizard/manifest.json` (default: ./.wizard/manifest.json)")
    check_p.add_argument("--registry-path", default=None,
                         help="Path to `wizard/registry/foundation-bundles.json` (default: cwd-relative)")
    check_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    check_p.set_defaults(func=cmd_upgrade_check)

    upgrade_p = sub.add_parser("upgrade", help="Upgrade to a target version (plan-only preview or --apply)")
    upgrade_p.add_argument("--to", required=True, help="Target foundation_bundle_version (operator-explicit; no --latest)")
    upgrade_p.add_argument("--plan-only", action="store_true",
                           help="Preview the plan; performs no mutation.")
    upgrade_p.add_argument("--apply", action="store_true",
                           help="Apply the foundation-document upgrade (operator-explicit). "
                                "Operator-edited files are kept and the new version saved for review.")
    upgrade_p.add_argument("--ack", action="store_true",
                           help="With --apply: acknowledge adopting the new version of a warn-on-drift "
                                "file you have edited (your version is backed up first).")
    upgrade_p.add_argument("--manifest-path", default=None,
                           help="Path to operator-project `.wizard/manifest.json`")
    upgrade_p.add_argument("--registry-path", default=None,
                           help="Path to `wizard/registry/foundation-bundles.json`")
    upgrade_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    upgrade_p.set_defaults(func=cmd_upgrade)

    plan_p = sub.add_parser("upgrade-plan",
                            help="Synonym for `upgrade --to VERSION --plan-only` (plan-only at v0)")
    plan_p.add_argument("--to", required=True, help="Target foundation_bundle_version")
    plan_p.add_argument("--manifest-path", default=None)
    plan_p.add_argument("--registry-path", default=None)
    plan_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    plan_p.set_defaults(func=cmd_upgrade_plan)

    su_p = sub.add_parser(
        "self-update",
        help="Guarded update of the installed wizard toolkit itself (verify -> backup -> swap)",
    )
    su_mode = su_p.add_mutually_exclusive_group()
    su_mode.add_argument("--check", action="store_true",
                         help="Verify only (origin + lineage + clean tree); report; change nothing. (default)")
    su_mode.add_argument("--apply", action="store_true",
                         help="Verify, back up the toolkit, swap to the verified version, and record it. "
                              "The new version is used on your NEXT session (safe ordering).")
    su_p.add_argument("--toolkit-dir", default=None,
                      help="Path to the installed wizard toolkit (default: the directory this engine runs from)")
    su_p.add_argument("--operator-dir", default=None,
                      help="Path to the operator project holding .wizard/update-source.json (default: cwd)")
    su_p.add_argument("--to-commit", default=None,
                      help="Candidate commit to update to (default: current toolkit HEAD)")
    su_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    su_p.set_defaults(func=cmd_self_update)

    sup_p = sub.add_parser(
        "self-upgrade",
        help="Operator-reach upgrade: refresh the tool to the approved version, then apply it "
             "(self-update -> re-run -> apply, in one operator-approved step)",
    )
    sup_p.add_argument("--to", required=True,
                       help="Target foundation_bundle_version (operator-explicit; no --latest)")
    sup_mode = sup_p.add_mutually_exclusive_group()
    sup_mode.add_argument("--apply", action="store_true",
                          help="Perform the combined refresh-and-apply (this command mutates).")
    sup_mode.add_argument("--plan-only", action="store_true",
                          help="Read-only preview of what applying would change "
                               "(writes nothing, refreshes nothing, applies nothing).")
    sup_p.add_argument("--expect-commit", default=None,
                       help="(with --apply) Fail closed unless the live-resolved source commit "
                            "matches this token from a prior --plan-only preview — so you apply "
                            "exactly what you previewed.")
    sup_p.add_argument("--manifest-path", default=None,
                       help="Path to operator-project `.wizard/manifest.json` (default: ./.wizard/manifest.json)")
    sup_p.add_argument("--registry-path", default=None,
                       help="Path to `wizard/registry/foundation-bundles.json`")
    sup_p.add_argument("--toolkit-dir", default=None,
                       help="Path to the installed wizard toolkit (default: the directory this engine runs from)")
    sup_p.add_argument("--operator-dir", default=None,
                       help="Path to the operator project (default: derived from --manifest-path)")
    sup_p.add_argument("--fetch-remote", default=None,
                       help="Git remote the self-update fetches from (default: origin). Advanced/testing.")
    sup_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON to stdout")
    sup_p.set_defaults(func=cmd_self_upgrade)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
