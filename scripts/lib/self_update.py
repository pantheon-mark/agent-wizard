"""Guarded toolkit self-update — the `wizard self-update` contract.

This is the SEPARATE, explicit, operator-initiated step that brings the installed
update toolkit (the public clone of the distribution repo) current. It is decoupled
from the assistant's data-only update cycle on purpose: a freshly-published engine is
NEVER downloaded-and-executed in the same run that fetches it. The CURRENTLY-INSTALLED,
known-good engine performs verify + backup + swap; the new code runs only on the
operator's NEXT invocation. This avoids the central hazard of a self-verifying,
self-executing updater bricking a non-technical operator's system mid-update.

Safety contract (`--apply`, all gates fail-closed):
  1. read the pinned source from `.wizard/update-source.json` (read-only to the AI).
  2. VERIFY (every gate must pass, else a typed fail-closed status + honest message):
       - the configured canonical owner/repo URL matches the pinned source;
       - transport is HTTPS;
       - the toolkit's ACTUAL git remote resolves to the expected canonical URL;
       - the candidate commit is a DESCENDANT of last_known_good_commit
         (`git merge-base --is-ancestor`), so no history rewrite / no floating ref;
       - the local toolkit working tree is CLEAN (refuse a dirty tree).
  3. BACK UP the toolkit directory before touching anything (a timestamped sibling),
     and report a zero-CLI-skill rollback the operator can run by hand.
  4. perform the update (fetch + checkout the verified candidate commit) touching ONLY
     the toolkit directory — NEVER operator-project files.
  5. record the new last-known-good commit.
  6. HONEST wording: verified origin + lineage + integrity, NOT a cryptographic signature.

Stdlib-only (subprocess to the real `git`); pip-install-free.
"""

import datetime as _dt
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from upgrade import UpdateStatus, status_exit_code  # type: ignore
from update_source import (  # type: ignore
    UpdateSourceError,
    load_update_source,
    record_last_known_good_commit,
    _normalize_repo_url,
)
from update_resolution import (  # type: ignore
    UpdateResolutionError,
    load_update_resolution,
)
from resolution_verify import verify_fetched_against_resolution  # type: ignore


def self_update_exit_code(result: "SelfUpdateResult") -> int:
    """The CLI exit code for a self-update result. Routed through this module's own
    `UpdateStatus`/`status_exit_code` pair so the enum identity always matches the table
    (the CLI may import the engine under a different module path, which would otherwise
    create a distinct enum class)."""
    return status_exit_code(result.status)


# Honest authenticity ceiling — surfaced verbatim in operator-facing output so the
# trust posture is never overstated.
HONEST_CEILING_NOTE = (
    "This verified the expected GitHub origin, the commit lineage, and that the working "
    "tree was clean. This is NOT a cryptographic signature check."
)


@dataclass
class SelfUpdateResult:
    """Typed outcome of a self-update verify or apply.

    `status` is an UpdateStatus member (reused/extended); only OK statuses
    (UPDATE_AVAILABLE / CHECKED_CURRENT) mean a verified, safe-to-proceed state. Any
    other status is a fail-closed refusal — `applied` is False and nothing was changed.
    """
    status: UpdateStatus
    reason_code: str
    message: str
    applied: bool = False
    toolkit_dir: str = ""
    backup_dir: str = ""
    rollback_instructions: str = ""
    previous_commit: str = ""
    new_commit: str = ""
    checks: List[Tuple[str, bool, str]] = field(default_factory=list)  # (name, passed, detail)
    honest_ceiling: str = HONEST_CEILING_NOTE


# ===== git helpers (thin, testable; raise nothing — return (ok, stdout/err)) =====

def _git(toolkit_dir: Path, *args: str, timeout: int = 30) -> Tuple[bool, str]:
    """Run `git -C <toolkit_dir> <args>`. Returns (ok, combined-output). Never raises:
    a missing git / non-zero exit / timeout is reported as (False, message) so the
    caller fails closed with a typed status rather than crashing the operator session."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(toolkit_dir), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return (False, "git is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        return (False, f"git {' '.join(args)} timed out")
    except OSError as e:
        return (False, f"git {' '.join(args)} failed: {e}")
    out = (proc.stdout or "") + (proc.stderr or "")
    return (proc.returncode == 0, out.strip())


def _git_remote_url(toolkit_dir: Path, remote: str = "origin") -> Optional[str]:
    ok, out = _git(toolkit_dir, "remote", "get-url", remote)
    if not ok or not out:
        return None
    return out.strip()


def _working_tree_clean(toolkit_dir: Path) -> Tuple[bool, str]:
    ok, out = _git(toolkit_dir, "status", "--porcelain")
    if not ok:
        return (False, out)
    # "Clean" for the purpose of a safe checkout = no UNCOMMITTED CHANGES TO TRACKED FILES
    # (the only thing a fetch+checkout of a descendant could lose). UNTRACKED files (porcelain
    # `??` lines — e.g. a macOS `.DS_Store`, an operator's scratch note) are NOT at risk and
    # must NOT block the update: git checkout/reset to a descendant never deletes them, and a
    # gate that tripped on `.DS_Store` would refuse self-update on essentially every real macOS
    # toolkit. So ignore `??` lines and fail only on tracked modifications (staged/unstaged).
    tracked = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith("??")]
    return (not tracked, "\n".join(tracked))


def _is_ancestor(toolkit_dir: Path, ancestor: str, descendant: str) -> bool:
    """True iff `ancestor` is an ancestor of (or equal to) `descendant` — i.e. the
    candidate descends from last-known-good. Uses git's own merge-base check."""
    ok, _ = _git(toolkit_dir, "merge-base", "--is-ancestor", ancestor, descendant)
    return ok


def _rev_parse(toolkit_dir: Path, ref: str) -> Optional[str]:
    ok, out = _git(toolkit_dir, "rev-parse", ref)
    if not ok or not out:
        return None
    return out.strip()


def rollback_to_previous(toolkit_dir: Path, previous_commit: str, *, timeout: int = 30) -> Tuple[bool, str]:
    """Programmatic rollback after a failed post-checkout step (e.g. pin-write): restore the
    toolkit to its previous commit via `git checkout <previous_commit>`. Returns (ok, detail);
    if this itself fails, the pre-update backup dir is the durable recovery state the caller
    surfaces to the operator. Never raises."""
    if not previous_commit:
        return (False, "no previous commit to roll back to")
    return _git(toolkit_dir, "checkout", previous_commit, timeout=timeout)


def fetch_ref(toolkit_dir: Path, ref: str, *, remote: str = "origin", timeout: int = 60) -> Tuple[bool, str]:
    """`git fetch <remote> <ref>` — bring the approved commit's objects into the toolkit before
    checkout (the A+ target commit may not be present locally yet). Returns (ok, detail); never
    raises (git missing / unreachable remote -> (False, message)) so the caller fails closed."""
    return _git(toolkit_dir, "fetch", remote, ref, timeout=timeout)


def resolve_remote_commit(
    toolkit_dir: Path, source_url: str, ref: str, *, timeout: int = 30
) -> Optional[str]:
    """Resolve a remote ref to its EXACT commit SHA via `git ls-remote <source_url> <ref>`
    (Option A+ engine-commit binding). Read-only — no fetch, no checkout: it only asks the
    remote what <ref> currently points to, so `check` can bind the exact commit the operator
    approves and `self-update` later checks out precisely that commit.

    Returns the 40-hex SHA, or None on ANY git failure (git missing / unreachable source /
    unknown ref / unexpected output) so the caller fails CLOSED with a could-not-determine
    status rather than guessing a commit."""
    ok, out = _git(toolkit_dir, "ls-remote", source_url, ref, timeout=timeout)
    if not ok or not out:
        return None
    # ls-remote prints "<sha>\t<refname>" per matching ref; take the first line's sha.
    first = out.splitlines()[0].split()
    sha = first[0].strip().lower() if first else ""
    if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha):
        return sha
    return None


# ===== verification (the fail-closed gates) =====

def verify_self_update(
    toolkit_dir: Path,
    operator_project_dir: Path,
    *,
    candidate_commit: Optional[str] = None,
) -> SelfUpdateResult:
    """Run the fail-closed verification gates WITHOUT changing anything.

    Returns a SelfUpdateResult whose status is:
      - SOURCE_UNCONFIGURED   : no/invalid `.wizard/update-source.json`.
      - UPDATE_SOURCE_TAMPERED: non-HTTPS, or the toolkit's git remote does not resolve
                                to the pinned canonical owner/repo URL.
      - TOOLKIT_UNVERIFIED    : the toolkit is not a git repo / git unavailable / dirty
                                working tree (cannot establish a safe base to update from).
      - CANDIDATE_UNVERIFIED  : the candidate commit does not exist or is not a descendant
                                of last_known_good_commit (history rewrite / wrong lineage).
      - CHECKED_CURRENT       : verified; the toolkit is already at the candidate (nothing to do).
      - UPDATE_AVAILABLE      : verified; safe to apply (candidate descends from current).
    """
    checks: List[Tuple[str, bool, str]] = []

    # 1. read the pinned source (read-only to the AI).
    try:
        source = load_update_source(operator_project_dir)
    except UpdateSourceError as e:
        return SelfUpdateResult(
            status=UpdateStatus.SOURCE_UNCONFIGURED,
            reason_code="update_source_unreadable",
            message=(
                "Cannot update the tool: no usable update source is configured. "
                f"{e}"
            ),
            toolkit_dir=str(toolkit_dir),
            checks=[("read_update_source", False, str(e))],
        )
    checks.append(("read_update_source", True, "pinned source loaded"))

    expected_url = source["https_url"]
    last_known_good = source.get("last_known_good_commit", "")

    # 2a. transport must be HTTPS (load_update_source already enforces this; re-assert).
    if not expected_url.startswith("https://"):
        return SelfUpdateResult(
            status=UpdateStatus.UPDATE_SOURCE_TAMPERED,
            reason_code="non_https_transport",
            message="Cannot update the tool: the configured update source is not HTTPS.",
            toolkit_dir=str(toolkit_dir),
            checks=checks + [("https_transport", False, expected_url)],
        )
    checks.append(("https_transport", True, expected_url))

    # 2b. the toolkit must actually be a git repo with a resolvable remote.
    if not (toolkit_dir / ".git").exists():
        return SelfUpdateResult(
            status=UpdateStatus.TOOLKIT_UNVERIFIED,
            reason_code="toolkit_not_a_git_repo",
            message=(
                "Cannot update the tool: the update tool directory is not a git "
                f"checkout, so it cannot be verified or updated ({toolkit_dir})."
            ),
            toolkit_dir=str(toolkit_dir),
            checks=checks + [("toolkit_is_git_repo", False, str(toolkit_dir))],
        )
    checks.append(("toolkit_is_git_repo", True, str(toolkit_dir)))

    # 2c. the toolkit's ACTUAL remote must resolve to the pinned canonical URL.
    actual_remote = _git_remote_url(toolkit_dir)
    if actual_remote is None:
        return SelfUpdateResult(
            status=UpdateStatus.TOOLKIT_UNVERIFIED,
            reason_code="toolkit_remote_unresolvable",
            message=(
                "Cannot update the tool: its git remote could not be read, so its "
                "origin cannot be verified."
            ),
            toolkit_dir=str(toolkit_dir),
            checks=checks + [("remote_resolves", False, "no origin remote")],
        )
    if _normalize_repo_url(actual_remote) != _normalize_repo_url(expected_url):
        return SelfUpdateResult(
            status=UpdateStatus.UPDATE_SOURCE_TAMPERED,
            reason_code="remote_origin_mismatch",
            message=(
                "Refusing to update the tool: the tool's actual download origin "
                f"({actual_remote}) does not match the trusted, pinned origin "
                f"({expected_url}). Nothing was changed."
            ),
            toolkit_dir=str(toolkit_dir),
            checks=checks + [("remote_matches_pinned_origin", False,
                              f"actual={actual_remote} expected={expected_url}")],
        )
    checks.append(("remote_matches_pinned_origin", True, actual_remote))

    # 2d. the working tree must be clean (refuse a dirty toolkit).
    clean, status_out = _working_tree_clean(toolkit_dir)
    if not clean:
        return SelfUpdateResult(
            status=UpdateStatus.TOOLKIT_UNVERIFIED,
            reason_code="toolkit_working_tree_dirty",
            message=(
                "Refusing to update the tool: it has uncommitted local changes. "
                "Updating now could lose them. Nothing was changed."
            ),
            toolkit_dir=str(toolkit_dir),
            checks=checks + [("working_tree_clean", False, status_out or "dirty")],
        )
    checks.append(("working_tree_clean", True, "clean"))

    current_commit = _rev_parse(toolkit_dir, "HEAD") or ""

    # 2e. candidate lineage. If no explicit candidate is given, the candidate is the
    # current HEAD (a verify-only run with nothing newer staged → CHECKED_CURRENT).
    candidate = candidate_commit or current_commit
    if not candidate:
        return SelfUpdateResult(
            status=UpdateStatus.CANDIDATE_UNVERIFIED,
            reason_code="candidate_unresolvable",
            message="Cannot update the tool: no candidate commit could be resolved.",
            toolkit_dir=str(toolkit_dir),
            checks=checks + [("candidate_resolves", False, "empty")],
        )
    # candidate must be a real object in the repo.
    resolved_candidate = _rev_parse(toolkit_dir, candidate)
    if resolved_candidate is None:
        return SelfUpdateResult(
            status=UpdateStatus.CANDIDATE_UNVERIFIED,
            reason_code="candidate_not_in_repo",
            message=(
                "Refusing to update the tool: the candidate version could not be found "
                "in the verified download. Nothing was changed."
            ),
            toolkit_dir=str(toolkit_dir),
            checks=checks + [("candidate_in_repo", False, candidate)],
        )
    checks.append(("candidate_in_repo", True, resolved_candidate))

    # If we have a recorded last-known-good, the candidate MUST descend from it (no
    # history rewrite, no floating ref). A placeholder / unset last-known-good means a
    # first bootstrap update — we then require the candidate to be a descendant of the
    # CURRENT HEAD instead (still forward-only), and the apply records the lineage.
    lineage_base = last_known_good if _rev_parse(toolkit_dir, last_known_good) else current_commit
    lineage_base_resolved = _rev_parse(toolkit_dir, lineage_base) if lineage_base else None
    if lineage_base_resolved:
        if not _is_ancestor(toolkit_dir, lineage_base_resolved, resolved_candidate):
            return SelfUpdateResult(
                status=UpdateStatus.CANDIDATE_UNVERIFIED,
                reason_code="candidate_not_descendant",
                message=(
                    "Refusing to update the tool: the candidate version does not "
                    "continue from the last known-good version (its history does not "
                    "line up). This can indicate a rewritten or wrong source. Nothing "
                    "was changed."
                ),
                toolkit_dir=str(toolkit_dir),
                checks=checks + [("candidate_descends_from_known_good", False,
                                  f"base={lineage_base_resolved} candidate={resolved_candidate}")],
            )
        checks.append(("candidate_descends_from_known_good", True,
                       f"base={lineage_base_resolved}"))

    if resolved_candidate == current_commit:
        return SelfUpdateResult(
            status=UpdateStatus.CHECKED_CURRENT,
            reason_code="toolkit_already_current",
            message="The update tool is already up to date. Nothing to update.",
            toolkit_dir=str(toolkit_dir),
            previous_commit=current_commit,
            new_commit=current_commit,
            checks=checks,
        )

    return SelfUpdateResult(
        status=UpdateStatus.UPDATE_AVAILABLE,
        reason_code="verified_safe_to_apply",
        message=(
            "Verified the update tool's origin and version lineage. Safe to update. "
            + HONEST_CEILING_NOTE
        ),
        toolkit_dir=str(toolkit_dir),
        previous_commit=current_commit,
        new_commit=resolved_candidate,
        checks=checks,
    )


# ===== backup + rollback =====

def _timestamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d-%H%M%S")


def _backup_toolkit(toolkit_dir: Path) -> Tuple[Path, str]:
    """Copy the toolkit directory to a timestamped sibling `<toolkit>.bak-<ts>` BEFORE
    any change. Returns (backup_dir, plain-language rollback instructions). A zero-CLI-
    skill rollback: delete the (possibly broken) new toolkit dir and rename the backup
    back to the original name."""
    ts = _timestamp()
    backup_dir = toolkit_dir.parent / f"{toolkit_dir.name}.bak-{ts}"
    # If a same-second backup already exists (extremely unlikely), disambiguate.
    n = 1
    while backup_dir.exists():
        backup_dir = toolkit_dir.parent / f"{toolkit_dir.name}.bak-{ts}-{n}"
        n += 1
    shutil.copytree(toolkit_dir, backup_dir, symlinks=True)
    rollback = (
        "If anything stops working after this update, you can put the old version back "
        "by hand:\n"
        f"  1. Delete the folder:   {toolkit_dir}\n"
        f"  2. Rename the backup:   {backup_dir}  ->  {toolkit_dir}\n"
        "Then start a new session. (No command-line skill needed beyond delete + rename.)"
    )
    return backup_dir, rollback


# ===== apply (verify -> backup -> swap by the OLD engine; NEW code runs next time) =====

def apply_self_update(
    toolkit_dir: Path,
    operator_project_dir: Path,
    *,
    candidate_commit: Optional[str] = None,
    record_commit_fn=None,
) -> SelfUpdateResult:
    """Verify, back up, then update the toolkit to the verified candidate commit.

    SAFE ORDERING (load-bearing): every step here is performed by the CURRENTLY-INSTALLED
    engine. The freshly-fetched code is checked out but NOT executed in this run; it runs
    on the operator's NEXT invocation. Touches ONLY the toolkit directory; never an
    operator-project file.

    `record_commit_fn(new_commit)` is an optional callback the caller supplies to persist
    the new last-known-good commit into `.wizard/update-source.json` (which is read-only
    to the AI but writable by this guarded path). If omitted, the result still reports the
    new commit and the caller records it.
    """
    verified = verify_self_update(
        toolkit_dir, operator_project_dir, candidate_commit=candidate_commit,
    )
    if verified.status == UpdateStatus.CHECKED_CURRENT:
        return verified  # already current; nothing to do, no backup needed.
    if verified.status != UpdateStatus.UPDATE_AVAILABLE:
        # Any non-OK verify status is a fail-closed refusal — return it verbatim.
        return verified

    # 3. back up BEFORE touching anything.
    try:
        backup_dir, rollback = _backup_toolkit(toolkit_dir)
    except OSError as e:
        return SelfUpdateResult(
            status=UpdateStatus.TOOLKIT_UNVERIFIED,
            reason_code="backup_failed",
            message=(
                "Refusing to update the tool: could not make a backup first, so the "
                f"update was not started. Nothing was changed. ({e})"
            ),
            toolkit_dir=str(toolkit_dir),
            checks=verified.checks,
        )

    # 4. perform the update — checkout the verified candidate commit, toolkit only.
    target = verified.new_commit or candidate_commit
    ok, out = _git(toolkit_dir, "checkout", target)
    if not ok:
        return SelfUpdateResult(
            status=UpdateStatus.CANDIDATE_UNVERIFIED,
            reason_code="checkout_failed",
            message=(
                "The update could not be completed (the new version did not check out "
                "cleanly). Your old version is backed up and unchanged.\n\n" + rollback
            ),
            toolkit_dir=str(toolkit_dir),
            backup_dir=str(backup_dir),
            rollback_instructions=rollback,
            previous_commit=verified.previous_commit,
            checks=verified.checks + [("checkout_candidate", False, out)],
        )

    new_commit = _rev_parse(toolkit_dir, "HEAD") or target

    # 5. record the new last-known-good commit (via the caller-supplied writer; this
    #    guarded path is the only writer of the read-only update-source reference).
    recorded = False
    if record_commit_fn is not None:
        try:
            record_commit_fn(new_commit)
            recorded = True
        except Exception as e:  # noqa: BLE001 — best-effort; surfaced, never fatal here.
            verified.checks.append(("record_last_known_good", False, str(e)))

    message = (
        "Updated the tool to the verified new version. The new version will be used the "
        "next time you start a session (this run finished with the previous, known-good "
        "version, on purpose, for safety).\n\n"
        + HONEST_CEILING_NOTE
        + "\n\n" + rollback
    )
    return SelfUpdateResult(
        status=UpdateStatus.UPDATE_AVAILABLE,
        reason_code="self_update_applied",
        message=message,
        applied=True,
        toolkit_dir=str(toolkit_dir),
        backup_dir=str(backup_dir),
        rollback_instructions=rollback,
        previous_commit=verified.previous_commit,
        new_commit=new_commit,
        checks=verified.checks + [
            ("checkout_candidate", True, new_commit),
            ("record_last_known_good", recorded, new_commit if recorded else "deferred to caller"),
        ],
    )


def apply_self_update_with_resolution(
    toolkit_dir: Path,
    operator_project_dir: Path,
    *,
    fetch_remote: str = "origin",
    record_commit_fn=None,
) -> SelfUpdateResult:
    """Option A+ resolution-driven self-update. ORDERING (load-bearing):
    fetch -> verify (origin/lineage/clean) -> backup -> checkout the EXACT approved commit ->
    HEAD==approved -> CONTENT GATE (fetched registry+bundle+operator state == approved hashes)
    -> atomic pin -> handoff. Auto-rolls-back to the previous commit on a post-checkout failure
    (HEAD mismatch / content mismatch / pin failure). NEVER `applied=True` unless checkout,
    HEAD check, content gate, AND pin all succeed. Touches ONLY the toolkit dir; the new engine
    runs on the operator's NEXT invocation (os.execv re-exec is wired separately).

    `fetch_remote` is the git remote to fetch from (default "origin"; tests use a local remote).
    `record_commit_fn(commit)` overrides the pin writer (default records the new last-known-good
    into the operator's read-only update-source via the guarded path)."""
    registry_path = toolkit_dir / "registry" / "foundation-bundles.json"

    # 0. the operator-approved contract.
    try:
        resolution = load_update_resolution(operator_project_dir)
    except UpdateResolutionError as e:
        return SelfUpdateResult(
            status=UpdateStatus.SOURCE_UNCONFIGURED, reason_code="no_approved_resolution",
            message=f"Cannot apply an update: no approved update was found. {e}",
            toolkit_dir=str(toolkit_dir),
        )

    previous_commit = _rev_parse(toolkit_dir, "HEAD") or ""
    target = resolution.target_public_commit_sha

    # 1. fetch the approved commit's objects (no checkout yet).
    ok, out = fetch_ref(toolkit_dir, resolution.source_ref, remote=fetch_remote)
    if not ok:
        return SelfUpdateResult(
            status=UpdateStatus.TOOLKIT_UNVERIFIED, reason_code="fetch_failed",
            message=f"Could not download the update. Nothing was changed. ({out})",
            toolkit_dir=str(toolkit_dir), previous_commit=previous_commit,
        )

    # 2. fail-closed verify gates (origin / lineage / clean) for the EXACT approved commit.
    verified = verify_self_update(toolkit_dir, operator_project_dir, candidate_commit=target)
    if verified.status == UpdateStatus.CHECKED_CURRENT:
        return verified  # already at the approved commit; nothing to do.
    if verified.status != UpdateStatus.UPDATE_AVAILABLE:
        return verified  # any non-OK verify status is a fail-closed refusal.

    # 3. back up BEFORE touching anything.
    try:
        backup_dir, rollback = _backup_toolkit(toolkit_dir)
    except OSError as e:
        return SelfUpdateResult(
            status=UpdateStatus.TOOLKIT_UNVERIFIED, reason_code="backup_failed",
            message=f"Refusing to apply: could not make a backup first. Nothing was changed. ({e})",
            toolkit_dir=str(toolkit_dir), previous_commit=previous_commit,
        )

    # 4. checkout the EXACT approved commit.
    ok, out = _git(toolkit_dir, "checkout", target)
    if not ok:
        return SelfUpdateResult(
            status=UpdateStatus.CANDIDATE_UNVERIFIED, reason_code="checkout_failed",
            message=("The update did not check out cleanly. Your old version is backed up and "
                     "unchanged.\n\n" + rollback),
            toolkit_dir=str(toolkit_dir), backup_dir=str(backup_dir),
            rollback_instructions=rollback, previous_commit=previous_commit,
            checks=verified.checks + [("checkout_candidate", False, out)],
        )

    # 5. HEAD must be EXACTLY the approved commit (no surprise ref movement).
    head = _rev_parse(toolkit_dir, "HEAD") or ""
    if head != target:
        rollback_to_previous(toolkit_dir, previous_commit)
        return SelfUpdateResult(
            status=UpdateStatus.CANDIDATE_UNVERIFIED, reason_code="head_mismatch",
            message=("Refusing to apply: the checked-out version did not match the approved "
                     "commit. Rolled back to your previous version.\n\n" + rollback),
            toolkit_dir=str(toolkit_dir), backup_dir=str(backup_dir),
            rollback_instructions=rollback, previous_commit=previous_commit,
            checks=verified.checks + [("head_equals_approved", False, f"head={head} approved={target}")],
        )

    # 6. CONTENT GATE: the fetched toolkit + operator state must match the approved hashes.
    vr = verify_fetched_against_resolution(registry_path, operator_project_dir, resolution)
    if not vr.ok:
        rollback_to_previous(toolkit_dir, previous_commit)
        return SelfUpdateResult(
            status=UpdateStatus.CANDIDATE_UNVERIFIED, reason_code="resolution_mismatch",
            message=("Refusing to apply: what was downloaded does not match what you approved. "
                     "Rolled back to your previous version.\n\n"
                     + "; ".join(vr.failures) + "\n\n" + rollback),
            toolkit_dir=str(toolkit_dir), backup_dir=str(backup_dir),
            rollback_instructions=rollback, previous_commit=previous_commit,
            checks=verified.checks + [("resolution_content_match", False, f) for f in vr.failures],
        )

    # 7. atomic pin write. AUTO-ROLLBACK on failure; NEVER applied unless the pin succeeds.
    pin = record_commit_fn or (lambda c: record_last_known_good_commit(operator_project_dir, c))
    try:
        pin(target)
    except Exception as e:  # noqa: BLE001 — pin failure is fatal to the transaction.
        rolled, _ = rollback_to_previous(toolkit_dir, previous_commit)
        recovery = ("" if rolled else
                    f"\n\nAutomatic rollback ALSO failed; restore from the backup by hand:\n{rollback}")
        return SelfUpdateResult(
            status=UpdateStatus.TOOLKIT_UNVERIFIED, reason_code="pin_write_failed",
            message=(f"Refusing to complete the update: could not record the new version, so it "
                     f"was rolled back (NOT applied). ({e}){recovery}"),
            toolkit_dir=str(toolkit_dir), backup_dir=str(backup_dir),
            rollback_instructions=rollback, previous_commit=previous_commit,
            checks=verified.checks + [("record_last_known_good", False, str(e))],
        )

    # 8. success — fully applied + recorded. NEW engine runs on the operator's NEXT invocation.
    return SelfUpdateResult(
        status=UpdateStatus.UPDATE_AVAILABLE, reason_code="self_update_applied",
        message=("Updated the tool to the approved, verified new version. It will be used the "
                 "next time you start a session.\n\n" + HONEST_CEILING_NOTE + "\n\n" + rollback),
        applied=True, toolkit_dir=str(toolkit_dir), backup_dir=str(backup_dir),
        rollback_instructions=rollback, previous_commit=previous_commit, new_commit=target,
        checks=verified.checks + [
            ("checkout_candidate", True, target),
            ("resolution_content_match", True, "fetched == approved"),
            ("record_last_known_good", True, target),
        ],
    )


def render_self_update_result(result: SelfUpdateResult, *, json_mode: bool = False) -> str:
    """Operator-facing render. Renders from the typed status/message ONLY (never raw git
    logs in the headline). `json_mode` emits a structured dict for machine callers."""
    if json_mode:
        import json
        return json.dumps({
            "status": result.status.value,
            "reason_code": result.reason_code,
            "applied": result.applied,
            "message": result.message,
            "toolkit_dir": result.toolkit_dir,
            "backup_dir": result.backup_dir,
            "previous_commit": result.previous_commit,
            "new_commit": result.new_commit,
            "checks": [{"name": n, "passed": p, "detail": d} for (n, p, d) in result.checks],
            "honest_ceiling": result.honest_ceiling,
        }, indent=2, sort_keys=True) + "\n"
    return result.message + "\n"
