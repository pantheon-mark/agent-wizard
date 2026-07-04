#!/bin/bash
# Always-on commit-hygiene guard — the enforced backstop that makes "reversible
# because it is git-tracked" TRUE rather than assumed. A prior real run left ~a week
# of uncommitted, entangled work on disk with no clean commit to revert to; the
# safety net stated in prose (orchestrator session-close step 7) had simply not
# fired. This hook is that prose's enforced backstop (defense in depth).
#
# Wired in .claude/settings.json to TWO hook events (the model cannot self-edit
# .claude/** — permissions.deny blocks it — so this runs as generator-emitted,
# trusted config):
#   * SessionStart (a SECOND SessionStart entry, alongside upgrade_notice.sh):
#       surface-only. Reports "N uncommitted changes from prior sessions" plus any
#       already-tracked data/secret files (F-30) at orientation, via the
#       additionalContext envelope. It NEVER commits and NEVER blocks the session.
#   * SessionEnd:
#       runs the POLICY-AWARE COMMIT — stages and commits code / docs / state, and
#       NEVER data or secrets, so a session close can no longer leave work stranded
#       and uncommitted. Backstops orchestrator_prompt.md session-close step 7.
#
# THE SAFETY CRUX — the policy-aware commit (SessionEnd):
#   1. Code-vs-data classification. What is safe to commit = code / docs / state.
#      What must NEVER be committed = data / secrets (see security/gitignore_manifest.md
#      for the plain-language classification this script enforces). The classification
#      is: a path is "sensitive" (never-commit) if it is git-ignored by the project's
#      own .gitignore (the enforcement file), OR if it matches a built-in secret/data
#      pattern set below (defense in depth — so a MISCONFIGURED .gitignore that fails to
#      list a secret still cannot leak it through this guard). Everything else is
#      code/docs/state and is committed.
#   2. F-30 already-tracked detection. `.gitignore` only stops UNtracked files; a file
#      committed BEFORE its ignore rule existed stays tracked forever — illusory
#      protection (the estate had master_list_copy.csv tracked; policy stated, never
#      enforced). So the guard scans `git ls-files` for tracked paths that are now
#      git-ignored or match a sensitive pattern, `git rm --cached`s them (untracks them
#      WITHOUT deleting the operator's working file), and surfaces a HISTORY-SCRUB prompt
#      — untracking stops future commits but the secret still lives in past history until
#      scrubbed (git filter-repo / BFG). It never silently leaves a tracked secret.
#   3. It builds the add-list by ENUMERATING changes and FILTERING OUT every sensitive
#      path — so a sensitive path is never `git add`ed in the first place — then a
#      belt-and-suspenders backstop unstages anything sensitive that slipped in before
#      committing. The committed tree can never contain a data/secret file.
#
# FAIL-OPEN, ALWAYS. Every git error, missing tool, or internal bug degrades to a
# warning and exit 0. A commit-hygiene bug must never wedge or block a session. git
# legitimately returns non-zero for ordinary conditions (nothing staged, no repo), so
# we do NOT use `set -e`; the python core try/excepts everything and always exits 0.

command -v python3 >/dev/null 2>&1 || exit 0
command -v git >/dev/null 2>&1 || exit 0

# Read the hook stdin payload (carries hook_event_name). Consumed once here.
HOOK_INPUT="$(cat 2>/dev/null)"

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}" \
python3 - "$HOOK_INPUT" <<'PY' 2>/dev/null || exit 0
import sys, os, json, subprocess, fnmatch, datetime

def _out(s):
    sys.stdout.write(s)

try:
    try:
        event = json.loads(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else {}
    except Exception:
        event = {}
    hook_event = event.get("hook_event_name") if isinstance(event, dict) else None

    proj = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    def git(*args, check=False):
        return subprocess.run(
            ["git", "-C", proj, *args],
            capture_output=True, text=True,
        )

    # --- Fail-open gate: must be a git work tree, else silently do nothing. ---
    r = git("rev-parse", "--is-inside-work-tree")
    if r.returncode != 0 or r.stdout.strip() != "true":
        sys.exit(0)

    # --- Code-vs-data classification (the never-commit set) ------------------
    # Built-in secret/data patterns, enforced INDEPENDENTLY of .gitignore so a
    # misconfigured ignore file still cannot leak these through the guard. This mirrors
    # the Secrets + Privacy categories in security/gitignore_manifest.md. Errs toward
    # NOT committing data: a data file the operator genuinely wants tracked they commit
    # themselves — the guard's job is to never auto-commit data/secrets.
    SENSITIVE_BASENAME_GLOBS = [
        ".env", ".env.*", "*.env",
        "*.pem", "*.key", "*.p12", "*.pfx", "*.pkcs12", "*.keystore", "*.jks",
        "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*", "id_dsa", "id_ecdsa",
        "credentials.json", "*credentials*.json", "service-account*.json",
        "*.csv", "*.tsv", "*.xlsx", "*.xls",
        "*.sqlite", "*.sqlite3", "*.db", "*.parquet",
    ]
    SENSITIVE_PATH_MARKERS = ("logs/", "security/session_cookies/")

    def _norm(p):
        p = p.strip().strip('"')
        if p.startswith("./"):
            p = p[2:]
        return p

    def _matches_builtin(path):
        path = _norm(path)
        base = os.path.basename(path)
        if any(fnmatch.fnmatch(base, g) for g in SENSITIVE_BASENAME_GLOBS):
            return True
        parts = path.split("/")
        if parts and parts[0] in ("logs",):
            return True
        for m in SENSITIVE_PATH_MARKERS:
            if path == m.rstrip("/") or path.startswith(m):
                return True
        if "session_cookies/" in path:
            return True
        return False

    def _is_gitignored(path):
        # git check-ignore reports whether the ignore rules WOULD exclude this path —
        # true even for a path that is (wrongly) still tracked. That is exactly the
        # F-30 illusory-protection signal.
        return git("check-ignore", "-q", "--", path).returncode == 0

    def _is_sensitive(path):
        return _matches_builtin(path) or _is_gitignored(path)

    def _status_paths():
        # `git status --porcelain -z`: NUL-delimited "XY <path>[NUL<orig>]" records.
        r = git("status", "--porcelain", "-z")
        if r.returncode != 0:
            return None
        raw = r.stdout
        paths = []
        i = 0
        fields = raw.split("\x00")
        while i < len(fields):
            rec = fields[i]
            if not rec:
                i += 1
                continue
            xy = rec[:2]
            path = rec[3:]
            # Renames/copies (R/C) carry an extra NUL-separated original path field.
            if xy and (xy[0] in ("R", "C") or xy[1] in ("R", "C")):
                i += 1  # skip the original-path field that follows
            paths.append(path)
            i += 1
        return paths

    def _tracked_sensitive():
        r = git("ls-files", "-z")
        if r.returncode != 0:
            return []
        files = [f for f in r.stdout.split("\x00") if f]
        return [f for f in files if _is_sensitive(f)]

    # ============ SessionStart: surface-only clean-tree + F-30 check ==========
    if hook_event == "SessionStart":
        paths = _status_paths()
        n = len(paths) if paths is not None else 0
        tracked_bad = _tracked_sensitive()
        msgs = []
        if n > 0:
            msgs.append(
                "Commit hygiene: %d uncommitted change%s from prior work are on disk. "
                "Review and commit (or discard) them before starting new work, so there "
                "is a clean, revertable baseline." % (n, "" if n == 1 else "s")
            )
        if tracked_bad:
            msgs.append(
                "Data/secret files are already tracked by git and should not be: "
                + ", ".join(sorted(tracked_bad))
                + ". These need to be untracked (git rm --cached) and their history "
                "scrubbed — flag this to the operator."
            )
        if not msgs:
            sys.exit(0)  # clean tree, nothing tracked wrong -> stay silent
        # additionalContext envelope so a SessionStart hook's output reaches session context.
        _out(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": "  ".join(msgs),
            }
        }))
        sys.exit(0)

    # ============ SessionEnd (default): the policy-aware commit ===============
    # Runs for SessionEnd, and also if invoked with no/other event (manual backstop).
    scrub_note = None

    # --- F-30: untrack already-tracked data/secrets (rm --cached) ------------
    tracked_bad = _tracked_sensitive()
    if tracked_bad:
        rr = git("rm", "--cached", "-r", "--", *tracked_bad)
        # If rm --cached succeeded, prepare the history-scrub prompt.
        if rr.returncode == 0:
            scrub_note = (
                "[COMMIT HYGIENE — ACTION NEEDED] These data/secret files were already "
                "tracked by git and have now been untracked (git rm --cached; your working "
                "copies are untouched): " + ", ".join(sorted(tracked_bad)) + ". Untracking "
                "stops FUTURE commits, but they still exist in the repo's PAST HISTORY. If "
                "any contained real secrets or private data, scrub history (git filter-repo "
                "or BFG) and rotate anything exposed. Surface this to the operator; do not "
                "silently ignore it."
            )

    # --- Build the add-list: enumerate changes, FILTER OUT every sensitive path
    # (so a sensitive path is never `git add`ed at all), then add only the safe set. ---
    paths = _status_paths()
    if paths is None:
        # status failed — fail-open, but still surface any F-30 scrub note.
        if scrub_note:
            _out(scrub_note + "\n")
        sys.exit(0)

    safe = []
    for p in paths:
        p = _norm(p)
        if not p:
            continue
        if _is_sensitive(p):
            continue  # never add data/secrets
        safe.append(p)

    if safe:
        git("add", "--", *safe)

    # --- Backstop: unstage anything sensitive that slipped into the index -----
    r = git("diff", "--cached", "--name-only", "-z")
    staged = [f for f in r.stdout.split("\x00") if f] if r.returncode == 0 else []
    slipped = [f for f in staged if _is_sensitive(f) and f not in tracked_bad]
    if slipped:
        git("reset", "-q", "HEAD", "--", *slipped)

    # --- Commit only if something is staged. ---------------------------------
    if git("diff", "--cached", "--quiet").returncode != 0:
        today = datetime.date.today().isoformat()
        msg = ("Session %s: commit-hygiene backstop (code/docs/state; data/secrets "
               "excluded)" % today)
        cr = git("commit", "-q", "-m", msg)
        if cr.returncode != 0:
            _out("[COMMIT HYGIENE] Could not auto-commit outstanding work: "
                 + (cr.stderr.strip() or "unknown git error")
                 + ". Commit it manually before closing so there is a clean baseline.\n")

    if scrub_note:
        _out(scrub_note + "\n")

    sys.exit(0)
except SystemExit:
    raise
except Exception:
    # Fail-open: a bug here must never wedge or block a session.
    sys.exit(0)
PY

# python3 itself failing to run must not block the session.
exit 0
