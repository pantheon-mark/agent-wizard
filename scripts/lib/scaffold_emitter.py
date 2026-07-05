"""Base-scaffold emitter — emits the operator-project base scaffold from a
validated EmissionPlan into a STAGING directory.

Owns the 11 scaffold-template cells of the inherited corpus: the operator's
root files (CLAUDE.md, project_instructions.md, session_bootstrap.md, ...),
the operational directories (logs/, quality/, work/, docs/, security/,
archive/), and start-session.sh. It does NOT emit:
  - the foundation docs (documents/*) — those come from generator.generate_bundle
    (foundation-doc generation, wired separately);
  - the /agents/ runtime tree — that is agent_emitter.emit_agent_layer;
  - the wizard-internal _index.md catalogs (they describe the TEMPLATE tree, not
    the operator project);
  - quality/rules_library.md — that is the corpus single-home, owned by
    corpus_emitter.

Tier discipline: the scaffold model placeholders ({{MODEL_HIGH/STANDARD/FAST}})
carry RESOLVED model strings — they feed the operator's --model flag in
start-session.sh and the project_instructions.md tier->model map. (Agent PROMPTS
use tier NAMES via the separate {{MODEL_TIER_*}} family handled by agent_emitter.)

Interview-derived placeholders (financial / notification / user-profile / scale)
are gathered later during the operator interview; until then they resolve to
deterministic operator-configure defaults so the system is runnable now and the
operator fills real values during setup. A plan may override any default via its
free-form foundation_doc_inputs map; structural plan fields (project_name,
model_tiers) always win.

Stdlib-only, pip-install-free. Reuses generator._substitute_placeholders (strict
{{KEY}}, fail-fast on any unsubstituted placeholder).
"""

from pathlib import Path
from typing import Dict, List, Optional

from emission_plan import EmissionPlan  # type: ignore
from generator import _substitute_placeholders, PLACEHOLDER_RE  # type: ignore
from bundle_templates import (  # type: ignore
    operating_layer_source_version, _bundle_dir, bundle_has_operating_layer,
)


# Operational directories emitted verbatim-with-substitution (flat one level each).
# root/ maps to the staging root; the rest map to a same-named staging subdir.
SCAFFOLD_SUBDIRS = ("root", "logs", "quality", "work", "docs", "security", "archive", "deliverables")

# Subset of SCAFFOLD_SUBDIRS that are OPTIONAL — introduced in a later bundle version
# and absent from older bundles. scaffold_emitter._scaffold_sources already skips a
# missing dir gracefully; this set tells _verify_template_dependencies (in
# operator_system_emitter) to do the same rather than raising for bundles that
# legitimately predate the feature.
# deliverables/ was introduced in v0.7.0; older operating-layer bundles do not carry
# templates/deliverables/ and should not be rejected for that.
OPTIONAL_SCAFFOLD_SUBDIRS = frozenset({"deliverables"})

# Scaffold + operating-layer templates are now sourced from the versioned system
# bundle's templates/ tree (the single frozen template home), NOT the live working
# trees. These build-repo-relative constants are retained ONLY for the prewrite
# dependency check in operator_system_emitter and the unused-input scan; emission
# itself reads from the bundle (see _bundle_templates_root / emit_scaffold).
TEMPLATES_REL = "wizard/templates"
START_SESSION_TEMPLATE = "wizard/scripts/start_session_template.sh"
# Claude Code config emitted into the operator project's .claude/ so the system can SEE
# its actual context (statusline + context-monitor hook) instead of guessing. Static
# files (no {{placeholders}}); the .sh scripts are emitted executable.
CLAUDE_CONFIG_REL = "wizard/templates/claude_config"
CLAUDE_CONFIG_SCRIPTS = ("statusline.sh", "context_monitor.sh", "receipt_gate.sh",
                         "upgrade_notice.sh", "commit_hygiene.sh")

# Bundle-relative subpaths for the named scaffold scripts (their relpath inside the
# bundle's templates/ tree differs from the live build-repo layout).
_BUNDLE_START_SESSION_REL = "scripts/start_session_template.sh"
_BUNDLE_CLAUDE_CONFIG_REL = "claude_config"

# Files the scaffold layer must NOT emit (owned elsewhere or wizard-internal).
# env_template lives in the bundle (so the contract's .env template_path resolves)
# but .env is emitted EMPTY by operator_fill_emitter, not from this template — the
# scaffold walk must skip it.
EXCLUDE_BASENAMES = {"_index.md", "env_template"}
EXCLUDE_RELPATHS = {
    "quality/rules_library.md",  # corpus single-home (corpus_emitter)
    # security/capability_descriptors.json is emitted ONLY for a writes-back plan, by the
    # agent-layer emitter (agent_emitter._emit_capability_descriptor_set), gated exactly like the
    # external_write lib. The unconditional scaffold walk must NOT emit it — a read-only system
    # would otherwise get a dead descriptor set. This exclusion is inert until T9b copies the
    # template into the bundle's templates/security/; it is placed here now so the moment the
    # bundle carries it, the scaffold walk already skips it. (B2-T9a)
    "security/capability_descriptors.json",
}

# Source-basename -> emitted-basename renames.
RENAME = {"gitignore_template": ".gitignore"}

SCRIPT_MODE = 0o755


def _default_scaffold_inputs() -> Dict[str, str]:
    """Deterministic operator-configure defaults for every non-plan-derived
    scaffold placeholder. Honest placeholders for fields the operator supplies at
    setup; sensible concrete values for operational thresholds so the system
    is runnable immediately. No clock / no randomness (replay-deterministic)."""
    CONFIGURE = "(operator-configures during setup)"
    AT_SETUP = "(set at operator setup)"
    NONE_YET = "(none yet)"
    return {
        # --- identity / purpose ---
        "PROJECT_PURPOSE": "(operator-configures during setup — describe what this system is for)",
        "AUTONOMY_LEVEL": "2",
        # --- inherited operating principles (orchestrator overrides with the real
        # corpus-rendered block; this standalone default keeps the scaffold emittable) ---
        "INHERITED_OPERATING_PRINCIPLES":
            "Operating principles governing this system live in `quality/rules_library.md` "
            "(rules `OP-01`..`OP-NN`). Read them before acting.",
        # --- operational thresholds (concrete, runnable) ---
        "THREE_STRIKES_THRESHOLD": "3",
        "RETRY_THRESHOLD": "3",
        "DEFERRED_ALERT_THRESHOLD": "3",
        "STALE_DECISION_THRESHOLD_DAYS": "7",
        "PREFLIGHT_THRESHOLD": "50%",
        "MID_EXECUTION_THRESHOLD": "65%",
        "CONTEXT_WINDOW_LIMIT": "200000 tokens",
        "CONFIDENCE_FLAGGING_THRESHOLD": "medium",
        "CONFIDENCE_THRESHOLD": "medium",
        "GATE_CONFLICT_TIMEOUT": "24 hours",
        "DRIFT_ANALYSIS_CADENCE": "weekly",
        "NOTIFICATION_VERBOSITY": "standard",
        "QA_REPORTING_STYLE": "summary",
        "CHUNK_CONFIRMATION": "enabled",
        "BASH_AUTHORIZATION": "ask-first",
        "CREDENTIAL_CHECK_CADENCE": "quarterly",
        "ROTATION_LEAD_TIME_DAYS": "14",
        # --- scale tier ---
        "SCALE_TIER": "small",
        "SCALE_TIER_RATIONALE": CONFIGURE,
        "SCALE_TIER_BASIS": CONFIGURE,
        "SCALE_TIER_SET_DATE": AT_SETUP,
        # --- financial / automation budget (interview-derived via the
        # hitl_autonomy group, override the CONFIGURE fallbacks through foundation_doc_inputs.
        # Replaces the retired OVERAGE_PLAN_TYPE / SPEND_CEILING / INTENSIVE_THRESHOLD keys —
        # the dollar-ceiling-on-a-flat-plan model was a fiction; the honest guardrail is the
        # plan's separate monthly automation credit (Agent SDK credit pool), metered by estimate) ---
        "AUTOMATION_CREDIT_POOL": CONFIGURE,
        "PROJECT_AUTOMATION_BUDGET": CONFIGURE,
        "PROJECT_SHARE_POSTURE": "sole",
        "EXHAUSTION_BEHAVIOR": "wait",
        "PAYG_CAP": "n/a (not using paid overflow)",
        "INTENSIVE_OPERATION_THRESHOLD": CONFIGURE,
        "INTENSIVE_OPERATION_THRESHOLD_PCT": "10",
        # --- notifications (operator-supplied) ---
        "NTFY_TOPIC": CONFIGURE,
        "DIGEST_EMAIL": CONFIGURE,
        "DIGEST_CADENCE": "daily",
        # --- user profile (operator-supplied) ---
        "UP_TECHNICAL_LITERACY": CONFIGURE,
        "UP_INFORMATION_PREFERENCE": CONFIGURE,
        "UP_DECISION_PREFERENCE": CONFIGURE,
        "UP_DOMAIN_EXPERTISE": CONFIGURE,
        "UP_INVOLVEMENT_APPETITE": CONFIGURE,
        "UP_PROFILE_SUMMARY": CONFIGURE,
        # --- model tier notes (the resolved strings come from the plan) ---
        "MODEL_HIGH_NOTES": "highest-capability tier",
        "MODEL_STANDARD_NOTES": "balanced tier",
        "MODEL_FAST_NOTES": "fast/low-cost tier",
        "MODEL_MAPPING_VERIFIED_DATE": AT_SETUP,
        # --- dates / triggers (deterministic strings; no clock) ---
        "LAST_UPDATED_DATE": AT_SETUP,
        "LAST_UPDATED_TRIGGER": "wizard setup",
        "MANUAL_LAST_UPDATED": AT_SETUP,
        "LAST_SESSION_DATE": AT_SETUP,
        "FIRST_CONTEXT_CHECK_DATE": AT_SETUP,
        "FIRST_CREDENTIAL_CHECK_DATE": AT_SETUP,
        "FIRST_QUARTERLY_REVIEW_DATE": AT_SETUP,
        # --- github remote ---
        "GITHUB_REMOTE_URL": "(local-only — no remote configured)",
        # --- session-bootstrap live counters / state (fresh project) ---
        "ALERT_ACTIVE_COUNT": "0",
        "PENDING_DECISION_COUNT": "0",
        "REVIEW_QUEUE_COUNT": "0",
        "WORK_QUEUE_OPEN_COUNT": "0",
        "CURRENT_PHASE": "setup",
        "LAST_AGENT_RUN": NONE_YET,
        "LAST_SESSION_SUMMARY": NONE_YET,
        "NEXT_RECOMMENDED_ACTION": "First-boot setup: run the credential-setup skill to add the credentials your system needs (it will tell you if there are none), then start your first agent build.",
        "ITEMS_LEFT_INCOMPLETE": "(none)",
        "WORK_QUEUE_TOP_ITEM": NONE_YET,
        "CRITICAL_ALERT_NOTE": "(none)",
        # --- voice & style (operator-supplied) ---
        "TONE": CONFIGURE,
        "TECHNICAL_LEVEL": CONFIGURE,
        "EXPLANATION_DEPTH": CONFIGURE,
        "LENGTH_PREFERENCE": CONFIGURE,
        "LIST_STYLE": CONFIGURE,
        "TABLE_STYLE": CONFIGURE,
        # --- table-body / list-body placeholders -> empty (valid empty tables/lists) ---
        "AGENT_PERMISSION_ROWS": "",
        "CREDENTIAL_REFERENCE_ROWS": "",
        "CREDENTIAL_REGISTRY_ROWS": "",
        "VERSION_PIN_ROWS": "",
        "CRON_SCHEDULE_ROWS": "",
        "ADDITIONAL_MONITORING_ROWS": "",
        "CONDITION_TRIGGERED_ROWS": "",
        "DATE_TRIGGERED_ROWS": "",
        "INPUT_TYPE_INVENTORY": "",
        "DOMAIN_SENSITIVITY_SETTINGS": "",
        "SOURCE_REGISTRY_ROWS": "",
        # capability_descriptor_registry.md's QA-view row body (B1-2). No bundle template
        # references this placeholder yet (canonical-only per D-B1-a; bundle-cut at B2), so this
        # default is currently inert — seeded now so it resolves the moment the template is bundled.
        "CAPABILITY_DESCRIPTOR_REGISTRY_ROWS": "",
        # co-protected-workflows.md's projected "Registered capability workflows" row body
        # (B1-6). No bundle template references this placeholder yet (canonical-only per
        # D-B1-a; bundle-cut at B2), so this default is currently inert — seeded now so it
        # resolves the moment the template is bundled.
        "CO_PROTECTED_CAPABILITY_ROWS": "",
        "ADVISOR_ENTRIES": "",
        "AUTONOMOUS_ACTIONS": "",
        "TIER_1_ADDITIONS": "",
        "WIZARD_SETUP_STUBS": "",
        "ADDITIONAL_GITIGNORE_ENTRIES": "",
        "OPERATOR_OUTPUT_POINTER": "",
        "OUTPUT_TEMPLATES": "",
        "APPROVED_EXAMPLES": "",
        "ANTI_PATTERNS": "",
        # --- build-progress ledger (seeded from capability increments at assembly time;
        # defaults to empty so the template resolves when no increments are present) ---
        "BUILD_PROGRESS_ROWS": "",
        # --- ceremony-maturity seed (one probationary row per high-risk action class,
        # injected at assembly time; defaults to empty so the template resolves) ---
        "CEREMONY_MATURITY_ROWS": "",
    }


def _plan_derived_inputs(plan: EmissionPlan) -> Dict[str, str]:
    """Structural plan fields that always win over defaults."""
    return {
        "PROJECT_NAME": plan.project_name,
        "MODEL_HIGH": plan.model_tiers["high"],
        "MODEL_STANDARD": plan.model_tiers["standard"],
        "MODEL_FAST": plan.model_tiers["fast"],
    }


def build_scaffold_inputs(plan: EmissionPlan,
                          extra_inputs: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Merge precedence: defaults < plan.foundation_doc_inputs < extra_inputs <
    structural plan fields. `extra_inputs` lets the orchestrator supply
    emission-time values (e.g. the rendered inherited-principles block) without
    mutating the frozen plan."""
    merged: Dict[str, str] = dict(_default_scaffold_inputs())
    for k, v in (plan.foundation_doc_inputs or {}).items():
        merged[k] = str(v)
    for k, v in (extra_inputs or {}).items():
        merged[k] = str(v)
    merged.update(_plan_derived_inputs(plan))
    return merged


def _bundle_templates_root(build_repo_root: Path, version: Optional[str] = None) -> Path:
    """The bundle templates/ tree that is the single frozen home for the scaffold +
    operating-layer templates (the contract-bearing bundle, not the live working tree).

    When `version` is supplied (the plan's bundle_version), templates are sourced from
    that specific bundle.  When omitted the function falls back to the legacy
    operating_layer_source_version() discovery for callers (e.g. scaffold_template_placeholders)
    that do not have a plan at hand."""
    if version is None:
        version = operating_layer_source_version(str(build_repo_root))
    return _bundle_dir(version, build_repo_root) / "templates"


def _scaffold_sources(build_repo_root: Path, version: Optional[str] = None) -> List[Path]:
    """Collect the scaffold template files to emit (excluding the never-emit set).

    Sourced from the bundle's frozen templates/ tree (single home), not the live
    working tree. `version` pins the bundle to use; if omitted the legacy
    operating_layer_source_version() discovery is used."""
    templates_root = _bundle_templates_root(build_repo_root, version)
    sources: List[Path] = []
    for sub in SCAFFOLD_SUBDIRS:
        d = templates_root / sub
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            if f.name in EXCLUDE_BASENAMES:
                continue
            rel = f"{sub}/{f.name}"
            if rel in EXCLUDE_RELPATHS:
                continue
            sources.append(f)
    return sources


def _dest_for(src: Path, sub: str, staging_dir: Path) -> Path:
    """Map a template source to its staging destination. root/ -> staging root;
    other dirs keep their name; apply basename renames (gitignore_template)."""
    name = RENAME.get(src.name, src.name)
    if sub == "root":
        return staging_dir / name
    return staging_dir / sub / name


def scaffold_template_placeholders(build_repo_root: Path) -> set:
    """Union of {{KEY}} placeholders every scaffold template (the SCAFFOLD_SUBDIRS
    template tree + start-session.sh) references.

    This is the set of input keys the scaffold layer CAN consume: emit_scaffold
    merges plan.foundation_doc_inputs into its substitution map, so any fdi key
    that matches a scaffold-template placeholder is consumed by this emitter. The
    orchestrator unions this with the foundation-doc placeholders + the explicit
    assembler-consumed set to decide which fdi keys went genuinely unused (the
    accurate full-system unused-input warning). Computed by static scan of the
    template bodies so it stays correct as templates evolve — no hardcoded list."""
    keys: set = set()
    for src in _scaffold_sources(build_repo_root):
        keys |= set(PLACEHOLDER_RE.findall(src.read_text(encoding="utf-8")))
    sess_src = _bundle_templates_root(build_repo_root) / _BUNDLE_START_SESSION_REL
    keys |= set(PLACEHOLDER_RE.findall(sess_src.read_text(encoding="utf-8")))
    return keys


def emit_scaffold(plan: EmissionPlan, staging_dir: Path, build_repo_root: Path,
                  extra_inputs: Optional[Dict[str, str]] = None) -> List[Path]:
    """Emit the base operator scaffold for `plan` into `staging_dir`. Returns paths written.

    When the emitted bundle_version carries no operating-layer templates (no
    system-artifacts.json — e.g. v0.4.0 or v0.5.0), the scaffold files are simply
    absent from the emitted tree (foundation-only fallback). Foundation docs are emitted
    separately via emit_foundation_docs and are always present."""
    if not bundle_has_operating_layer(plan.bundle_version, build_repo_root):
        # Foundation-only bundle: scaffold files are absent; nothing to emit here.
        return []

    inputs = build_scaffold_inputs(plan, extra_inputs)
    written: List[Path] = []

    for src in _scaffold_sources(build_repo_root, plan.bundle_version):
        sub = src.parent.name
        dest = _dest_for(src, sub, staging_dir)
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding="utf-8")
        result, _seen = _substitute_placeholders(content, inputs, template_name=src.name)
        dest.write_text(result, encoding="utf-8")
        written.append(dest)

    # start-session.sh (from the frozen bundle templates/scripts/), resolved-model + executable.
    bundle_templates_root = _bundle_templates_root(build_repo_root, plan.bundle_version)
    sess_src = bundle_templates_root / _BUNDLE_START_SESSION_REL
    sess_dest = staging_dir / "start-session.sh"
    content = sess_src.read_text(encoding="utf-8")
    result, _seen = _substitute_placeholders(content, inputs, template_name="start-session.sh")
    sess_dest.write_text(result, encoding="utf-8")
    sess_dest.chmod(SCRIPT_MODE)
    written.append(sess_dest)

    # .claude/ config (statusline + context-monitor hook + settings) — emitted verbatim
    # (static, no placeholders); the shell scripts are made executable. Sourced from the
    # frozen bundle templates/claude_config/.
    claude_src = bundle_templates_root / _BUNDLE_CLAUDE_CONFIG_REL
    claude_dir = staging_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    for name in ("settings.json",) + CLAUDE_CONFIG_SCRIPTS:
        src = claude_src / name
        if not src.is_file():
            # Operating-layer files are keyed to the bundle version: a bundle that does
            # not carry this .claude file (e.g. one predating the upgrade-notice hook)
            # gracefully skips it — matching the operating-layer absent-fallback — instead
            # of crashing on a missing optional file. Newer bundles that carry it emit it.
            continue
        dest = claude_dir / name
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        if name.endswith(".sh"):
            dest.chmod(SCRIPT_MODE)
        written.append(dest)

    return written
