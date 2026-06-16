"""Replay-capsule emitter — writes `.wizard/replay-capsule.json` into the operator
project so a future foundation-bundle upgrade can deterministically re-render the
foundation documents from the SAME inputs the project was first built from.

What the capsule carries:
  - the operator's foundation-doc inputs (`plan.foundation_doc_inputs`), so the
    upgrade path can render the CURRENT-version docs and confirm they match the
    manifest base_hash (replay-conformance) before it renders the target version.
  - provenance pinning the inputs to one build: foundation_bundle_version,
    generator_version (the same 40-char SHA the manifest records), system_shape,
    foundation_only_mode, plus the canonicalization/hash-scheme stamps shared with
    the upgrade engine.

Privacy posture: the capsule holds the operator's interview answers, so before any
write it is run through a FAIL-CLOSED secret scan. If any value looks like a
credential / token / private-key, the emit is REFUSED with a message naming the
offending KEY (never the value) — credentials belong in .env, not interview
answers. The emitted .gitignore excludes the capsule by default (local-only unless
the operator opts in).

Determinism: pretty JSON with sorted keys + trailing newline; no clock / no
randomness. Stdlib-only, pip-install-free (operator/runtime path).
"""

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, List, Tuple

from emission_plan import EmissionPlan  # type: ignore
from upgrade import CANONICALIZATION_VERSION, HASH_ALGORITHM  # type: ignore


CAPSULE_SCHEMA_VERSION = "replay-capsule-v1"

REPLAY_CAPSULE_REL = ".wizard/replay-capsule.json"


class ReplayCapsuleError(Exception):
    """Raised when the replay capsule cannot be safely emitted — chiefly when a
    credential/token-shaped value is found in the foundation-doc inputs. Fail-closed:
    refuse to emit rather than persist a secret to disk."""


# --- Secret-scan rule set ---------------------------------------------------
#
# Rule-LEVEL detectors (not value-level): each describes a SHAPE of credential, so
# planting a fresh token of the same class is still caught. Tuned to avoid flagging
# ordinary business prose — the high-entropy heuristic only fires on a single
# unbroken token (no whitespace) that is both long AND high-entropy, which normal
# sentences (full of spaces + low per-char entropy) never are.

# Vendor / format-specific prefixes (anchored to a following token body so a bare
# mention of the prefix word in prose does not trip them).
_PREFIX_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("openai-style key (sk-)", re.compile(r"sk-[A-Za-z0-9_-]{16,}")),
    ("github token (ghp_/gho_/ghu_/ghs_)", re.compile(r"gh[pous]_[A-Za-z0-9]{16,}")),
    ("aws access key id (AKIA…)", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private key block (-----BEGIN …-----)", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("slack token (xox[baprs]-…)", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
]

# `key=value` credential assignments (case-insensitive key; value must be a
# non-trivial token, not an empty placeholder or a relationship word).
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
    r"client[_-]?secret|auth[_-]?token|bearer)\s*[=:]\s*[^\s'\"]{6,}"
)

# High-entropy long-token heuristic: a single whitespace-free run of credential-class
# characters, long enough + random enough that prose never produces it.
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9+/=_-]{32,}")
_ENTROPY_MIN_LEN = 32
_ENTROPY_BITS_PER_CHAR = 3.5  # english prose ~<3.0; random base64/hex ~4.5-6.0
_ENTROPY_MIN_DISTINCT = 16    # a 32-char run of few distinct symbols is not a secret


def _shannon_entropy_bits_per_char(s: str) -> float:
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _looks_high_entropy_token(token: str) -> bool:
    """True if `token` is a single long, high-entropy, high-cardinality run — the
    shape of an API key / hex digest, not of a word or a hyphenated phrase. Prose is
    excluded structurally: the token regex requires NO whitespace, so a sentence can
    never match as one token; on top of that we require both high per-char entropy
    AND many distinct characters, which ordinary identifiers (e.g. a long snake_case
    field name) fail."""
    if len(token) < _ENTROPY_MIN_LEN:
        return False
    if len(set(token)) < _ENTROPY_MIN_DISTINCT:
        return False
    return _shannon_entropy_bits_per_char(token) >= _ENTROPY_BITS_PER_CHAR


def _scan_value(value: Any) -> List[str]:
    """Return a list of human-readable reasons this value looks like a secret
    (empty list = clean). Recurses into list/dict containers so nested inputs are
    covered."""
    reasons: List[str] = []
    if isinstance(value, str):
        for label, pat in _PREFIX_PATTERNS:
            if pat.search(value):
                reasons.append(label)
        if _ASSIGNMENT_PATTERN.search(value):
            reasons.append("credential assignment (e.g. password=/token=/api_key=)")
        for token in _TOKEN_CHARS.findall(value):
            if _looks_high_entropy_token(token):
                reasons.append("high-entropy token (credential-shaped string)")
                break
    elif isinstance(value, dict):
        for v in value.values():
            reasons.extend(_scan_value(v))
    elif isinstance(value, (list, tuple)):
        for v in value:
            reasons.extend(_scan_value(v))
    return reasons


def scan_inputs_for_secrets(foundation_doc_inputs: dict) -> None:
    """Fail-closed pre-write guard. Scan every value in `foundation_doc_inputs` for
    credential/token-shaped strings. On ANY hit raise ReplayCapsuleError naming the
    offending KEY (never the value) and refusing to emit. Clean inputs return None."""
    hits: List[str] = []
    for key, value in foundation_doc_inputs.items():
        reasons = _scan_value(value)
        if reasons:
            # Dedupe while preserving order, so the message is stable + deterministic.
            seen: List[str] = []
            for r in reasons:
                if r not in seen:
                    seen.append(r)
            hits.append(f"{key!r} ({'; '.join(seen)})")
    if hits:
        raise ReplayCapsuleError(
            "refusing to write the replay capsule: credential/token-shaped value(s) "
            "found in foundation-doc inputs: " + ", ".join(sorted(hits)) + ". "
            "Credentials belong in .env, not in interview answers — remove the secret "
            "from the answer (reference it indirectly) and re-run, so the capsule never "
            "persists a secret to disk."
        )


def build_replay_capsule(plan: EmissionPlan) -> dict:
    """Build the replay-capsule dict from the emission plan. Pure function of the
    plan; deterministic. Provenance fields come from the SAME plan attributes the
    manifest emitter uses (no re-derivation): foundation_bundle_version =
    plan.bundle_version, generator_version = plan.generator_version (the 40-char SHA
    the manifest records), system_shape, foundation_only_mode."""
    return {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "foundation_bundle_version": plan.bundle_version,
        "generator_version": plan.generator_version,
        "system_shape": plan.system_shape,
        "foundation_only_mode": plan.foundation_only_mode,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "hash_algorithm": HASH_ALGORITHM,
        "foundation_doc_inputs": dict(plan.foundation_doc_inputs),
    }


def emit_replay_capsule(plan: EmissionPlan, staging_dir: Path,
                        build_repo_root: Path) -> Path:
    """Emit `.wizard/replay-capsule.json` into `staging_dir`. Runs the fail-closed
    secret scan FIRST (before any write); on a hit raises ReplayCapsuleError and
    writes nothing. Provenance is reused from `plan` (the same source the manifest
    uses), not re-derived. `build_repo_root` is accepted for signature parity with
    the other `.wizard/` emitters; the capsule needs nothing from it.

    Returns the path written. Deterministic: sorted keys + trailing newline; no
    clock / no randomness."""
    scan_inputs_for_secrets(plan.foundation_doc_inputs)  # fail-closed; raises before write
    doc = build_replay_capsule(plan)
    dest = staging_dir / REPLAY_CAPSULE_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dest
