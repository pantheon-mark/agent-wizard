"""Wizard-side strict-subset validator for foundation-bundle manifests.

Validates the F-9 generator-version identity field at a stdlib-safe subset
of the full build-side validation rule-set. Ships with the wizard
distribution; operators can run this check on their own `.wizard/manifest.yaml`
to catch common manifest mistakes before they reach the build-side
authoritative gate.

Stdlib-only: no PyYAML, no third-party deps. Wizard distribution stays
pip-install-free per the wizard-side stdlib-only discipline.

============================================================================
STRICT-SUBSET ASYMMETRY CONTRACT (per (M-2) drift mitigation)
============================================================================

This validator is a documented STRICT SUBSET of the build-side authoritative
validator at `tools/validate_foundation_bundle_manifest.py`.

    If a manifest PASSES this wizard-side check, it MAY still fail the
    build-side authoritative gate. Wizard-side coverage is intentionally
    narrower than build-side coverage.

    If a manifest FAILS this wizard-side check, it will ALSO fail the
    build-side authoritative gate. There is no input that passes wizard-side
    but fails on a check covered ONLY by wizard-side.

The asymmetry exists because build-side runs PyYAML (full YAML semantics +
cross-field invariants) while wizard-side runs stdlib (constrained-scope
line scanner). Wizard-side covers the high-value checks operators are most
likely to need before the build-side gate runs:

    - Top-level key uniqueness (catches duplicate-key authoring mistakes)
    - Top-level placement of `generator_version:` (catches misplaced field)
    - Non-empty value of `generator_version:` when present
    - 40-char hex format of `generator_version:` value
    - Coarse package/operator context detection from top-level field
      presence (detects operator-context via `files:` discriminator;
      package-context via `included_templates:` / `managed_files:` /
      `public_api:` / `status:` discriminators)

Build-side adds: cross-field invariants (e.g., generator_version REQUIRED
when foundation_bundle_version >= v1.0.0), deferral-comment-permission
logic, schema-version compatibility ranges, nested-structure validation.

If validation rules diverge in a way this asymmetry cannot honestly
represent, see the canonical foundation-versioning specification § 8.5
M-1 candidate-future-slice (externalized validation-rules contract).

============================================================================

Public API:
    validate_manifest(manifest_path: Path) -> ValidationResult
        Returns ValidationResult(passed: bool, context: str, failures: list).
        Never raises on validation outcome; raises ManifestValidatorError on
        I/O / read errors only.

CLI:
    python3 -m wizard.scripts.lib.manifest_validator <manifest-path>
    Exit 0 on PASS, 1 on FAIL, 2 on I/O error.
"""

import re
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Tuple


# Top-level field detection: a line where ANY non-whitespace character starts
# at column 0 and the line contains `:` after the key. Comments + blank lines
# excluded.
TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:")

# Match `generator_version:` at any indent (used to detect misplacement).
ANY_INDENT_GENVER_RE = re.compile(r"^(\s*)generator_version\s*:")

# 40-char hex (lowercase or uppercase per F-9 contract).
SHA_FORMAT_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class ManifestValidatorError(Exception):
    """Raised on I/O errors only; NOT raised on validation outcome."""


class ValidationResult(NamedTuple):
    passed: bool
    context: str  # 'package' | 'operator' | 'unknown'
    failures: List[str]  # empty when passed=True


def _read_lines(manifest_path: Path) -> List[str]:
    try:
        return manifest_path.read_text().splitlines()
    except FileNotFoundError as exc:
        raise ManifestValidatorError(f"manifest file not found: {manifest_path}") from exc
    except OSError as exc:
        raise ManifestValidatorError(f"cannot read manifest {manifest_path}: {exc}") from exc


def _strip_inline_comment(value_part: str) -> str:
    """Strip inline `# ...` comment from a value (rudimentary; doesn't handle
    `#` inside quoted strings, but value_part is expected to be a simple
    scalar for the fields we care about)."""
    # Find a `#` preceded by whitespace, OR `#` at start.
    idx = value_part.find("#")
    while idx > 0:
        if value_part[idx - 1].isspace():
            return value_part[:idx].rstrip()
        idx = value_part.find("#", idx + 1)
    if idx == 0:
        return ""
    return value_part.rstrip()


def _extract_top_level_keys(lines: List[str]) -> List[Tuple[int, str, str]]:
    """Extract (line_index, key, value_str) for top-level keys.

    Top-level = key starts at column 0 (no indent).
    Comments (lines whose first non-blank char is #) are skipped.
    Blank lines skipped.
    """
    out: List[Tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        m = TOP_LEVEL_KEY_RE.match(line)
        if not m:
            continue
        key = m.group(1)
        # Extract value part (everything after the first `:`).
        colon_idx = line.find(":")
        value_part = line[colon_idx + 1 :].strip()
        value_part = _strip_inline_comment(value_part)
        out.append((i, key, value_part))
    return out


def _detect_context(top_level_keys: List[Tuple[int, str, str]]) -> str:
    """Coarse context detection from top-level field presence.

    Operator manifest: has `files:` (plural, typically with hash baselines).
    Package manifest: has any of `included_templates:`, `managed_files:`,
    `public_api:`, or `status:`.
    Returns 'package' | 'operator' | 'unknown'.
    """
    keys = {k for _, k, _ in top_level_keys}
    has_files = "files" in keys
    has_package = bool(
        keys & {"included_templates", "managed_files", "public_api", "status"}
    )
    if has_files and not has_package:
        return "operator"
    if has_package and not has_files:
        return "package"
    if has_files and has_package:
        return "unknown"  # both — conflicting; let build-side resolve
    return "unknown"


def validate_manifest(manifest_path: Path) -> ValidationResult:
    """Validate manifest against the wizard-side strict-subset rules.

    Returns ValidationResult. Does not raise on validation failures.
    Raises ManifestValidatorError on I/O failures only.
    """
    lines = _read_lines(manifest_path)

    failures: List[str] = []
    top_level = _extract_top_level_keys(lines)
    context = _detect_context(top_level)

    # Rule (a): top-level key uniqueness.
    seen_keys: dict = {}
    for line_idx, key, _ in top_level:
        if key in seen_keys:
            failures.append(
                f"duplicate top-level key {key!r} (first at line {seen_keys[key]+1}, "
                f"again at line {line_idx+1})"
            )
        else:
            seen_keys[key] = line_idx

    # Rule (b): top-level-only `generator_version:` placement.
    # Scan ALL lines for any indented (column > 0) occurrence of
    # `generator_version:`; if found, flag as misplacement.
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        m = ANY_INDENT_GENVER_RE.match(line)
        if m:
            indent = m.group(1)
            if indent:  # non-empty indent = nested
                failures.append(
                    f"`generator_version:` found nested at line {i+1} (indent={len(indent)} "
                    "chars); must be top-level (column 0) only"
                )

    # Rule (c) + (d): if `generator_version:` is present at top-level, value
    # must be non-empty + match 40-char hex format.
    gen_ver_value: Optional[str] = None
    for _, key, value in top_level:
        if key == "generator_version":
            gen_ver_value = value
            break

    if gen_ver_value is not None:
        # Rule (c): non-empty
        if not gen_ver_value:
            failures.append("`generator_version:` value is empty")
        else:
            # Strip optional quoting (YAML allows `"abc"` or `'abc'`).
            stripped = gen_ver_value.strip("\"'")
            # Rule (d): 40-char hex format.
            if not SHA_FORMAT_RE.match(stripped):
                failures.append(
                    f"`generator_version:` value does not match 40-char hex format: "
                    f"got {gen_ver_value!r} (length after strip={len(stripped)})"
                )

    # Rule (e): coarse package/operator context detection.
    # Wizard-side does NOT enforce the cross-field invariant
    # "generator_version REQUIRED when foundation_bundle_version >= v1.0.0"
    # — that's a build-side responsibility per documented strict-subset
    # asymmetry. Wizard-side merely notes the context for diagnostic output.
    # However: for operator-context manifests (which require generator_version
    # unconditionally per F-9), wizard-side CAN catch the absent-field case
    # because it's an unconditional requirement, not a cross-field invariant.
    if context == "operator" and gen_ver_value is None:
        failures.append(
            "operator-project manifest missing required field `generator_version` "
            "(F-9 contract: REQUIRED unconditionally for wizard-generated operator "
            "bundles regardless of foundation_bundle_version)"
        )

    return ValidationResult(passed=(len(failures) == 0), context=context, failures=failures)


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write(
            "Usage: python3 -m wizard.scripts.lib.manifest_validator <manifest-path>\n"
        )
        return 2

    manifest_path = Path(sys.argv[1])
    try:
        result = validate_manifest(manifest_path)
    except ManifestValidatorError as exc:
        sys.stderr.write(f"IO ERROR: {exc}\n")
        return 2

    if result.passed:
        sys.stdout.write(f"PASS {manifest_path} (context={result.context})\n")
        return 0
    sys.stderr.write(f"FAIL {manifest_path} (context={result.context})\n")
    for failure in result.failures:
        sys.stderr.write(f"  - {failure}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
