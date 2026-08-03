"""Operator-invocable commands over the writer-state machinery -- the top layer.

It validates through the structural-state core and writes through the
acknowledgement store, and it is the only place those two meet for the purpose of
CHANGING something. That is what makes it the right home for an eligibility rule:
asking "what state is this writer in?" here costs nothing, because this layer
already depends on the core, whereas asking it from inside the store is what used
to close a two-way import cycle between the store and the state module.

Layering, in one line each:

    writer_state_core   structural state; imports no sibling.
    writer_ack_store    the records and the hash-validity rule; imports no sibling.
    _ext_write_state    the state SERVICE: structural state combined with the
                        recorded decisions, plus the reap and the advisory owner
                        derivation.
    writer_commands     this module. Validates via the core, writes via the store,
                        and deliberately does NOT depend on the service -- that
                        edge is the one whose absence keeps the graph a DAG.

Enforcement ceiling (disclosure): build-time + operator-as-approver, NOT a
runtime/OS sandbox -- the same ceiling every module in this package discloses. A
command here records an operator's decision; it does not make any writer safe.

Zoning note: listed in ``zones.SEALED_KERNEL_MODULE_PATHS`` because it imports
sibling kernel submodules, which is ordinary internal kernel wiring and is exactly
what that allowlist exists to declare. It imports no vendor SDK, constructs no
credential, names no adapter, and never calls ``run_operation``. Membership grants
NO capability the right to import it (that allowlist is the independent
``scan._CAPABILITY_ALLOWED_EXTERNAL_WRITE_SUBMODULES`` set).

Stdlib only -- no third-party dependencies. The only non-stdlib imports are two
sibling modules of this same trusted package, both themselves stdlib-only; it never
imports across the build/runtime boundary.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Spelled `import external_write.<submodule> as _x` rather than the
# `from external_write import <submodule>` form several older modules in this
# package use. Both mean the same thing to Python, but only this one is a form the
# sibling bypass scanner's sealed-kernel module-boundary rule actually matches — so
# this module's SEALED_KERNEL membership is load-bearing (remove the entry and the
# scan flags these two lines) rather than decorative. The counterfactual is
# asserted in test_external_write_writer_state_layers.py.
import external_write.writer_ack_store as _store
import external_write.writer_state_core as _core


def acknowledge_writer(project_root: str,
                       writer_relpath: str,
                       *,
                       operator_confirmation: str,
                       acknowledged_at: Optional[str] = None) -> Dict[str, Any]:
    """Record the operator's accepted-risk decision for ONE unrepairable writer.

    Fails closed, with a plain-language reason, when:
      * the confirmation is blank/whitespace-only (no silent acknowledgement);
      * the confirmation contains a newline or carriage return (paste-safety --
        the same fail-closed rule the acceptance CLI applies, since a line-split
        paste can otherwise truncate what the operator "said");
      * the writer file is absent or unreadable (nothing to bind a hash to);
      * there is no OPEN bespoke-writer entry for this relpath (no orphan
        records, and no pre-acknowledging a file that is not flagged).

    The four checks run in that order, which is the order they have always run in:
    what the operator reads when their confirmation is unusable must not depend on
    whether the file happened to be flagged.

    Propagates ``ExternalWriteStateReadError`` if the pending-migrations queue
    exists but cannot be read -- an unreadable queue must never present as "this
    file is not flagged" and quietly refuse for the wrong reason, nor as "it is
    flagged" and record against nothing.

    Returns the stored record. Idempotent per relpath: re-acknowledging replaces
    that writer's prior record rather than accumulating duplicates."""
    _store.validate_confirmation(operator_confirmation)
    content_sha256 = _store.require_writer_content_hash(project_root, writer_relpath)

    open_relpaths = {str(e.get("writer_relpath"))
                     for e in _core.open_bespoke_writer_migrations(project_root)}
    if writer_relpath not in open_relpaths:
        raise _store.WriterAcknowledgementError(
            f"nothing was recorded -- `{writer_relpath}` is not currently flagged as "
            "needing attention, so there is nothing to accept")

    return _store.put_acknowledgement_record(
        project_root, writer_relpath,
        content_sha256=content_sha256,
        operator_confirmation=operator_confirmation,
        acknowledged_at=acknowledged_at,
    )
