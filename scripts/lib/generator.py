"""Wizard generator pipeline — produces operator-project bundle from a source
foundation bundle + canned operator inputs.

Stdlib-only: no PyYAML, no third-party deps. Wizard distribution stays
pip-install-free per the wizard-side stdlib-only distribution boundary.

Design contracts:
    - Hash defaults + per-file managed/merge metadata + canonical file
      ordering come from the foundation-manifest-hash-baseline JSON contract
      at wizard/foundation-bundles/v0/contracts/foundation-manifest-hash-baseline-v1.json.
      The generator does NOT implement independent manifest validation rules;
      it delegates to the foundation-bundle-manifest validators at
      wizard/scripts/lib/manifest_validator.py (operator-side strict-subset
      check) and the build-side authoritative validator.
    - Generator-version identity (`generator_version:` field) comes from
      wizard/scripts/lib/generator_version.py:current_generator_version(
      require_clean=True) at emission time. The worktree at the build-repo
      root must be clean — dirty worktree state makes the recorded identity
      false provenance.
    - `source_commit` field is read verbatim from the source bundle's registry
      entry in wizard/registry/foundation-bundles.json. It is the source
      bundle's published commit, NOT the current build-repo HEAD. The two
      identifiers are distinct contracts.
    - Operator manifest is emitted as deterministic YAML text (NOT via
      yaml.dump, which would require PyYAML). Field ordering, indentation,
      and line endings are stable across runs.
    - Operator manifest carries a TIGHT field set: only foundation_bundle_version,
      source_commit, generator_version, and the per-file files map. Package-
      manifest fields (foundation_schema_version, agent_contract_version,
      release_date, status, managed_files, included_templates, public_api)
      are deliberately kept disjoint from the operator-manifest surface so
      downstream context auto-detection can distinguish operator vs package
      manifests unambiguously.
    - Seven foundation docs are emitted: vision.md, prd.md (schema-only stub),
      approach.md, execution_plan.md, technical_architecture.md, test_cases.md,
      audit_framework.md.

Public API:
    generate_bundle(
        source_version: str,
        target_dir: Path,
        inputs: Dict[str, str],
        build_repo_root: Path,
        require_clean: bool = True,
    ) -> GenerationResult

Stub PRD section list lives in PRD_STUB_SECTIONS module constant. A parity
test guards drift between the constant and the canonical YAML schema at
wizard/foundation-bundles/v0.3.0/schemas/section-schema.yaml.
"""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional


# ============================================================================
# PRD stub section list (hardcoded; parity-tested against the canonical YAML schema)
# ============================================================================
# The generator runtime is stdlib-only and cannot parse YAML directly. The PRD
# section titles are mirrored here as a module constant; a build-time parity
# test reads the canonical YAML schema at
# wizard/foundation-bundles/v0.3.0/schemas/section-schema.yaml and asserts these
# titles match. Drift is caught at CI.
PRD_STUB_SECTIONS = [
    ("vision_link", "Vision Link"),
    ("persona_jtbd", "Persona / JTBD"),
    ("functional_requirements", "Functional Requirements"),
    ("non_functional_requirements", "Non-Functional Requirements"),
]


# ============================================================================
# Constants
# ============================================================================

# Strict placeholder pattern: {{KEY}} where KEY is uppercase + underscores only.
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")


class GeneratorError(Exception):
    """Raised when generation fails for any reason; carries a human-readable message."""


class GenerationResult(NamedTuple):
    success: bool
    manifest_path: Path
    paths_written: List[Path]
    errors: List[str]  # empty when success=True


# ============================================================================
# Source-bundle resolution
# ============================================================================

def _resolve_source_bundle(
    source_version: str,
    build_repo_root: Path,
) -> Dict[str, str]:
    """Look up the source bundle's registry entry; return its dict.

    Reads wizard/registry/foundation-bundles.json (JSON; stdlib). Raises
    GeneratorError if the registry is missing, malformed, or has no entry for
    source_version.
    """
    registry_path = (
        build_repo_root / "wizard" / "registry" / "foundation-bundles.json"
    )
    if not registry_path.exists():
        raise GeneratorError(
            f"foundation-bundles registry not found at {registry_path}"
        )
    try:
        registry = json.loads(registry_path.read_text())
    except json.JSONDecodeError as exc:
        raise GeneratorError(
            f"foundation-bundles registry at {registry_path} is not valid JSON: {exc}"
        )
    bundles = registry.get("bundles", [])
    for entry in bundles:
        if entry.get("foundation_bundle_version") == source_version:
            return entry
    available = [b.get("foundation_bundle_version") for b in bundles]
    raise GeneratorError(
        f"source bundle version {source_version!r} not found in registry; "
        f"available: {available}"
    )


def _read_required_foundation_docs(
    build_repo_root: Path,
) -> List[Dict[str, str]]:
    """Read required_foundation_docs ordering from the hash-baseline JSON contract.

    Returns the list verbatim; downstream code uses it to (a) determine which
    files to emit, (b) order the operator manifest's files map, (c) populate
    per-file managed_by / local_modifications / merge_strategy.
    """
    contract_path = (
        build_repo_root
        / "wizard"
        / "foundation-bundles"
        / "v0"
        / "contracts"
        / "foundation-manifest-hash-baseline-v1.json"
    )
    if not contract_path.exists():
        raise GeneratorError(
            f"foundation-manifest-hash-baseline contract not found at {contract_path}"
        )
    try:
        contract = json.loads(contract_path.read_text())
    except json.JSONDecodeError as exc:
        raise GeneratorError(
            f"hash-baseline contract at {contract_path} is not valid JSON: {exc}"
        )
    required = contract.get("required_foundation_docs")
    if not isinstance(required, list) or not required:
        raise GeneratorError(
            f"hash-baseline contract at {contract_path} missing or empty "
            "required_foundation_docs field"
        )
    return required


# ============================================================================
# Template substitution
# ============================================================================

def _substitute_placeholders(
    content: str,
    inputs: Dict[str, str],
    template_name: str,
) -> str:
    """Substitute {{KEY}} placeholders in content using inputs dict.

    - Fail-fast on missing keys (raises GeneratorError naming the template
      and missing keys).
    - Substitutions are not rescanned (no recursion).
    - Strict placeholder pattern: uppercase + underscores only.

    Does NOT enforce all-inputs-used; the caller can warn about unused keys
    after collecting substituted-key sets.
    """
    missing: List[str] = []
    seen: set = set()

    def _replace(match: "re.Match[str]") -> str:
        key = match.group(1)
        seen.add(key)
        if key not in inputs:
            missing.append(key)
            # Return original to allow continued scanning (still fail at end).
            return match.group(0)
        return str(inputs[key])

    result = PLACEHOLDER_RE.sub(_replace, content)
    if missing:
        # Deduplicate preserving order.
        unique_missing: List[str] = []
        seen_missing: set = set()
        for m in missing:
            if m not in seen_missing:
                seen_missing.add(m)
                unique_missing.append(m)
        raise GeneratorError(
            f"template {template_name!r} references undefined placeholder(s): "
            f"{unique_missing}"
        )
    return result


# ============================================================================
# PRD schema-only stub emission
# ============================================================================

def _emit_prd_stub(inputs: Dict[str, str]) -> str:
    """Emit prd.md as a schema-only stub.

    No template content is substituted: the wizard does not ship a template
    for prd.md at this release — the operator authors content per the
    canonical section schema. The stub contains:

        - YAML frontmatter (foundation_doc_type, foundation_schema_version,
          wizard_version_compatible, managed_by)
        - An "OPERATOR-AUTHORED CONTENT REQUIRED" header
        - Section headings derived from PRD_STUB_SECTIONS (hardcoded;
          parity-tested against the canonical YAML section schema)
        - A deferred-population note per section
    """
    wizard_version = inputs.get("WIZARD_VERSION", "v0.3.0")
    lines: List[str] = []
    lines.append("---")
    lines.append("foundation_doc_type: prd")
    lines.append("foundation_schema_version: v0.2")
    lines.append(f'wizard_version_compatible: "{wizard_version}"')
    lines.append("managed_by: operator")
    lines.append("---")
    lines.append("")
    lines.append("# Product Requirements (PRD)")
    lines.append("")
    lines.append("> **OPERATOR-AUTHORED CONTENT REQUIRED.** This document is "
                 "a schema-only stub at generation time. No template content "
                 "ships for prd.md at this foundation bundle release — the "
                 "operator authors content for each section below per the "
                 "canonical section schema at "
                 "`wizard/foundation-bundles/v0.3.0/schemas/section-schema.yaml` "
                 "(prd entry).")
    lines.append("")
    for _section_id, section_title in PRD_STUB_SECTIONS:
        lines.append(f"## {section_title}")
        lines.append("")
        lines.append("_Deferred — operator-authored content required._")
        lines.append("")
    # Ensure trailing newline only (no double trailing).
    return "\n".join(lines).rstrip() + "\n"


# ============================================================================
# Manifest emission (deterministic text; no yaml.dump)
# ============================================================================

def _emit_manifest_text(
    foundation_bundle_version: str,
    source_commit: str,
    generator_version: str,
    files_map: List[Dict[str, str]],
) -> str:
    """Emit operator manifest as deterministic YAML text.

    Tight field set — only:
        - foundation_bundle_version
        - source_commit
        - generator_version
        - files map (per-file managed / base_hash / current_hash_last_seen /
          local_modifications / merge_strategy)

    NO package-manifest fields (foundation_schema_version, agent_contract_version,
    release_date, status, managed_files, included_templates, public_api).

    Format conventions:
        - 2-space indentation
        - Field order fixed (per the call sites here)
        - Trailing newline at end of file
        - YAML strings unquoted unless they contain colons or other YAML
          metacharacters; for our limited field set (semver, SHAs, enum-like
          values), unquoted plain scalars are unambiguous.
    """
    lines: List[str] = []
    lines.append(f"foundation_bundle_version: {foundation_bundle_version}")
    lines.append(f"source_commit: {source_commit}")
    lines.append(f"generator_version: {generator_version}")
    lines.append("files:")
    for entry in files_map:
        path = entry["path"]
        lines.append(f"  {path}:")
        lines.append(f"    managed: true")
        lines.append(f"    base_hash: sha256:{entry['base_hash']}")
        lines.append(
            f"    current_hash_last_seen: sha256:{entry['current_hash_last_seen']}"
        )
        lines.append(f"    local_modifications: {entry['local_modifications']}")
        lines.append(f"    merge_strategy: {entry['merge_strategy']}")
    return "\n".join(lines) + "\n"


# ============================================================================
# Main generator entry point
# ============================================================================

def generate_bundle(
    source_version: str,
    target_dir: Path,
    inputs: Dict[str, str],
    build_repo_root: Path,
    require_clean: bool = True,
    generator_version_override: Optional[str] = None,
) -> GenerationResult:
    """Generate an operator-project bundle from a source foundation bundle.

    Args:
        source_version: foundation_bundle_version of the source bundle
            (e.g., "v0.3.0"). Must exist in wizard/registry/foundation-bundles.json.
        target_dir: directory to write the operator-project bundle to. Will
            create target_dir, target_dir/foundation/, and target_dir/.wizard/.
        inputs: dict mapping placeholder KEY (uppercase + underscores) to
            substitution value. Must cover all placeholders referenced by the
            6 template-backed foundation docs (the 7th, prd.md, ships as
            schema-only stub and consumes only the WIZARD_VERSION key from
            inputs as optional).
        build_repo_root: build-repo root path. Used to (a) read registry;
            (b) read the hash-baseline contract; (c) read templates;
            (d) invoke the generator-version-identity helper to record
            generator_version.
        require_clean: passed through to the generator-version-identity helper.
            Default True per the emission-time clean-worktree contract.
            Set False ONLY for development/debugging.
        generator_version_override: when not None, skip the helper and use
            this value directly. Used by tests for byte-identical reproduction
            with fixed provenance.

    Returns:
        GenerationResult(success, manifest_path, paths_written, errors)

    Raises:
        GeneratorError for any failure (registry / contract / template /
        helper / write errors).
    """
    # Import the generator-version helper lazily so tests can mock it before
    # import.
    if generator_version_override is None:
        from generator_version import current_generator_version  # type: ignore

    # 1. Resolve source bundle registry entry (extract source_commit verbatim
    # from the registry — the source bundle's published commit).
    registry_entry = _resolve_source_bundle(source_version, build_repo_root)
    source_commit = registry_entry["source_commit"]
    source_bundle_path = (
        build_repo_root / registry_entry["path"]
    ).resolve()
    if not source_bundle_path.exists():
        raise GeneratorError(
            f"source bundle directory not found at {source_bundle_path}"
        )

    templates_dir = source_bundle_path / "templates"
    if not templates_dir.exists():
        raise GeneratorError(
            f"source bundle templates directory not found at {templates_dir}"
        )

    # 2. Read required_foundation_docs from the hash-baseline contract
    # (canonical ordering + per-file managed metadata).
    required_docs = _read_required_foundation_docs(build_repo_root)

    # 3. Compute generator_version via the helper (clean-worktree enforcement
    # at emission time per the helper's contract).
    if generator_version_override is not None:
        generator_version = generator_version_override
    else:
        generator_version = current_generator_version(
            build_repo_root, require_clean=require_clean
        )

    # 4. Generate foundation docs (6 from templates + 1 prd.md stub).
    paths_written: List[Path] = []
    files_map_entries: List[Dict[str, str]] = []

    foundation_dir = target_dir / "foundation"
    foundation_dir.mkdir(parents=True, exist_ok=True)

    for required in required_docs:
        rel_path = required["path"]  # e.g. "foundation/vision.md"
        if not rel_path.startswith("foundation/"):
            raise GeneratorError(
                f"unexpected required-doc path shape {rel_path!r}; expected "
                "'foundation/<name>.md'"
            )
        doc_name = rel_path[len("foundation/"):]

        if doc_name == "prd.md":
            # Schema-only stub.
            content = _emit_prd_stub(inputs)
        else:
            # Template-backed substitution.
            template_path = templates_dir / doc_name
            if not template_path.exists():
                raise GeneratorError(
                    f"required template not found in source bundle: {template_path}"
                )
            template_content = template_path.read_text()
            content = _substitute_placeholders(
                template_content, inputs, template_name=doc_name
            )

        out_path = target_dir / rel_path
        out_path.write_text(content)
        paths_written.append(out_path)

        # Compute per-file hash.
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        files_map_entries.append(
            {
                "path": rel_path,
                "base_hash": content_hash,
                "current_hash_last_seen": content_hash,
                "local_modifications": required["local_modifications"],
                "merge_strategy": required["merge_strategy"],
            }
        )

    # 5. Emit operator manifest (deterministic text; tight field set).
    manifest_text = _emit_manifest_text(
        foundation_bundle_version=source_version,
        source_commit=source_commit,
        generator_version=generator_version,
        files_map=files_map_entries,
    )

    wizard_dir = target_dir / ".wizard"
    wizard_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = wizard_dir / "manifest.yaml"
    manifest_path.write_text(manifest_text)
    paths_written.append(manifest_path)

    return GenerationResult(
        success=True,
        manifest_path=manifest_path,
        paths_written=paths_written,
        errors=[],
    )


# ============================================================================
# Self-test entry (optional smoke)
# ============================================================================

if __name__ == "__main__":
    # Self-import smoke: confirm module loads and constants exist.
    sys.stdout.write(
        f"generator.py loaded; PRD_STUB_SECTIONS has {len(PRD_STUB_SECTIONS)} entries\n"
    )
    sys.exit(0)
