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
#   1. Code-vs-data classification, FAIL-SAFE / deny-by-default. The guard's #1 invariant
#      is NEVER auto-commit data or secrets, so it auto-commits ONLY what it can
#      POSITIVELY classify as safe = code / docs / known config (see
#      security/gitignore_manifest.md for the plain-language classification this script
#      enforces). A path is auto-committed only if it matches the built-in SAFE allowlist
#      (source/doc/config-source extensions, known code/config basenames, or the system's
#      own state/config at a KNOWN path such as .claude/settings.json or
#      .wizard/manifest.json). Anything it CANNOT positively classify — data-shaped files,
#      unknown extensions, ambiguous paths, a `.json` that is not a known config file — is
#      NOT committed and is SURFACED for an explicit operator decision (never silently
#      committed, never silently dropped). This is deny-by-default: a NEW data extension
#      nobody enumerated is refused because it is not on the safe list, not allowed because
#      it is not on a deny list. A separate built-in secret/data DENY set is still enforced
#      (defense in depth) so a MISCONFIGURED .gitignore cannot leak a secret and so a data
#      file is refused even under a known config path.
#   2. F-30 already-tracked detection. `.gitignore` only stops UNtracked files; a file
#      committed BEFORE its ignore rule existed stays tracked forever — illusory
#      protection (the estate had master_list_copy.csv tracked; policy stated, never
#      enforced). So the guard scans `git ls-files` for tracked paths that are now
#      git-ignored or match a sensitive pattern, `git rm --cached`s them (untracks them
#      WITHOUT deleting the operator's working file), and surfaces a HISTORY-SCRUB prompt
#      — untracking stops future commits but the secret still lives in past history until
#      scrubbed (git filter-repo / BFG). It never silently leaves a tracked secret.
#   3. It builds the add-list by ENUMERATING changes and keeping ONLY the positively-safe
#      paths — so a data/secret/ambiguous path is never `git add`ed in the first place;
#      those are collected and SURFACED instead. A belt-and-suspenders backstop then
#      unstages anything staged that is not positively safe (except the F-30 rm --cached
#      deletions) and surfaces it too. The committed tree can never contain a data/secret
#      file, and nothing is ever silently discarded.
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

    # --- Code-vs-data classification (FAIL-SAFE / deny-by-default) -----------
    # Two independent sets:
    #   (A) a POSITIVE SAFE allowlist -> the ONLY things auto-committed;
    #   (B) a built-in secret/data DENY set -> hard never-commit, used for F-30
    #       already-tracked detection AND to refuse a data/secret file even when it
    #       sits under a known config path.
    # Anything that is neither git-ignored nor positively safe is SURFACED for an
    # explicit operator decision (never committed, never silently dropped).

    # (B) Built-in secret/data patterns, enforced INDEPENDENTLY of .gitignore so a
    # misconfigured ignore file still cannot leak these through the guard. Mirrors the
    # Secrets + Data categories in security/gitignore_manifest.md.
    SENSITIVE_BASENAME_GLOBS = [
        ".env", ".env.*", "*.env",
        "*.pem", "*.key", "*.p12", "*.pfx", "*.pkcs12", "*.keystore", "*.jks",
        "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*", "id_dsa", "id_ecdsa",
        "credentials.json", "*credentials*.json", "service-account*.json",
        # data / dataset / dump formats — never auto-committed anywhere:
        "*.csv", "*.tsv", "*.xlsx", "*.xls",
        "*.sqlite", "*.sqlite3", "*.db", "*.parquet",
        "*.jsonl", "*.ndjson", "*.pkl", "*.pickle", "*.npy", "*.npz",
        "*.dat", "*.feather", "*.arrow", "*.avro", "*.h5", "*.hdf5",
    ]
    SENSITIVE_PATH_MARKERS = ("logs/", "security/session_cookies/")

    # (A) Positively-safe allowlist. A data format NEVER appears here.
    #   - source / doc / config-SOURCE extensions (human-authored, not data);
    #   - known code/config basenames that carry no or a non-safe extension;
    #   - the system's own state/config addressable by a KNOWN path — this is the ONLY
    #     way a .json (or other non-safe-extension config) is auto-committed.
    SAFE_EXTS = {
        # scripts / source
        ".py", ".sh", ".bash", ".zsh", ".fish", ".pl", ".rb",
        ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
        ".go", ".rs", ".java", ".kt", ".c", ".cc", ".cpp", ".h", ".hpp",
        ".cs", ".php", ".lua", ".r", ".swift", ".scala",
        # documentation / markup
        ".md", ".markdown", ".rst", ".adoc", ".html", ".htm",
        ".css", ".scss", ".sass", ".less",
        # configuration SOURCE (human-authored config, not data)
        ".yml", ".yaml", ".toml", ".cfg", ".ini", ".conf", ".properties",
    }
    SAFE_BASENAMES = {
        ".gitignore", ".gitattributes", ".editorconfig", ".dockerignore",
        ".gitmodules", "makefile", "dockerfile", "license", "readme",
        "requirements.txt", "constraints.txt",
    }
    KNOWN_CONFIG_PATHS = {
        ".claude/settings.json", ".claude/settings.local.json",
        ".wizard/manifest.json",
    }
    KNOWN_CONFIG_PREFIXES = (".claude/", ".wizard/")

    def _norm(p):
        p = p.strip().strip('"')
        if p.startswith("./"):
            p = p[2:]
        return p

    def _ext(base):
        # lowercase extension incl. the dot; "" for a dotfile (.gitignore) or no-ext file.
        i = base.rfind(".")
        return base[i:].lower() if i > 0 else ""

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
        # The hard never-commit signal (built-in secret/data OR git-ignored). Used for
        # F-30 already-tracked detection and SessionStart surfacing.
        return _matches_builtin(path) or _is_gitignored(path)

    def _is_safe_to_commit(path):
        # The POSITIVE gate: True only for things we can positively classify as safe to
        # auto-commit. A data/secret file is never safe — even under a known config path.
        p = _norm(path)
        base = os.path.basename(p)
        if _matches_builtin(p):
            return False
        if base.lower() in SAFE_BASENAMES:
            return True
        if _ext(base) in SAFE_EXTS:
            return True
        if p in KNOWN_CONFIG_PATHS:
            return True
        for pre in KNOWN_CONFIG_PREFIXES:
            if p.startswith(pre):
                return True
        return False

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

    # --- Build the add-list (FAIL-SAFE): auto-commit ONLY positively-safe paths.
    # Everything that is neither git-ignored nor positively safe is SURFACED for an
    # explicit operator decision — never committed, never silently dropped. ---
    paths = _status_paths()
    if paths is None:
        # status failed — fail-open, but still surface any F-30 scrub note.
        if scrub_note:
            _out(scrub_note + "\n")
        sys.exit(0)

    safe = []
    surface = []
    for p in paths:
        p = _norm(p)
        if not p:
            continue
        if _is_gitignored(p):
            continue  # deliberately excluded by the operator's .gitignore — not noise
        if _is_safe_to_commit(p):
            safe.append(p)
        else:
            surface.append(p)  # data-shaped / unknown / ambiguous -> operator decides

    if safe:
        git("add", "--", *safe)

    # --- Backstop (also fail-safe): unstage anything staged that is NOT positively safe,
    # except the F-30 rm --cached deletions we intentionally staged above. Anything
    # unstaged here is surfaced too, so nothing is ever silently dropped. ---
    r = git("diff", "--cached", "--name-only", "-z")
    staged = [f for f in r.stdout.split("\x00") if f] if r.returncode == 0 else []
    slipped = [f for f in staged if not _is_safe_to_commit(f) and f not in tracked_bad]
    if slipped:
        git("reset", "-q", "HEAD", "--", *slipped)
        for f in slipped:
            if f not in surface:
                surface.append(f)

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

    # --- Surface everything that was NOT auto-committed (fail-safe requirement). ------
    if surface:
        _out(
            "[COMMIT HYGIENE — REVIEW NEEDED] These changed files were NOT auto-committed "
            "because the guard could not positively classify them as safe (code / docs / "
            "known config). They may be data or secrets. Nothing here was committed and "
            "nothing was discarded — review each and either commit it yourself (if it is "
            "code/config the guard did not recognize) or move/ignore it (if it is data or "
            "a secret):\n  "
            + "\n  ".join(sorted(set(surface))) + "\n"
        )

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
