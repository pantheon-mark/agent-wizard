"""Kernel-supplied, lineage-typed evidence — the substrate a per-op_kind
EVIDENCE PREDICATE (`adapter_registry.AdapterDispatch.verify_apply_landed` /
`verify_undo_restored` / `verify_durability`) evaluates (Task 1, B4/T1 —
v0.12.0 Slice 1).

This is the mechanism-only half of the fix that later closes F-38 (proof-time,
Task 2) and F-41 (run-time, Task 3): a "verified" claim must be EARNED from
observed round-trip evidence, not asserted. This module builds ONLY the
evidence TYPE. Constructing a real `AdapterEvidence` — from a live read-only
observer (run-time) or a captured evidence file the kernel loads itself
(proof-time) — is the KERNEL's job, wired in those later tasks; nothing here
does that construction or that loading.

------------------------------------------------------------------------------
Anti-tautology property (extends verifiers.py's lineage lock)
------------------------------------------------------------------------------
`verifiers.py`'s existing lineage lock rejects a post-write verification
record whose DECLARED source lineage overlaps a registered verifier's
forbidden inputs — a structural check on a declaration. This module adds a
STRONGER, more structural guarantee for the new evidence predicate: the
predicate's signature is `(self, evidence) -> bool` — there is no path, ref,
or filename argument anywhere in that call. A predicate cannot open an
arbitrary file, hit a live surface, or otherwise reach outside what it was
handed, because there is no argument through which such a reach could even be
expressed — not merely a declaration the caller trusted. The KERNEL (not the
predicate, and not this module) is solely responsible for materializing an
`AdapterEvidence`'s `poststate`/`prestate` before ever calling the predicate;
by the time the predicate runs, all it has is already-observed data plus a
declared `source_lineage` describing where that data came from.

`source_lineage` reuses `contracts.SourceLineage` — the SAME lineage
vocabulary the Authority-clause post-write verification record already uses
(pre_write_sources / post_write_sources / forbidden_verification_inputs) —
rather than inventing a parallel lineage shape. A later task (proof-time
validation) is expected to check this declared lineage against the
op_kind's registered verifier the same way `verifiers.validate_
postwrite_verification` already does for the Authority clause; this task
only carries the field, it does not itself enforce the overlap check (that
enforcement lives in verifiers.py already, for the record it protects — this
module's OWN structural guarantee is the missing-path-argument property
above, which needs no additional runtime check to be true).

------------------------------------------------------------------------------
Shape-neutral by design (Global Constraint #4)
------------------------------------------------------------------------------
`poststate` / `prestate` are opaque, adapter-defined mappings: this module
does not know or care what keys are inside them. A Gmail predicate might read
`poststate["is_trashed"]` / `poststate["matches_prestate"]` (see
adapters_gmail.py); a field/spreadsheet-shaped predicate might read
`poststate["value"]` against `prestate["value"]`. Common convention (not
enforced here — enforcement of any convention would reintroduce a Gmail- or
field-shaped assumption into this shared substrate): an adapter MAY choose to
carry a boolean like `poststate["poststate_matches_expected"]` when its own
apply/undo verdict reduces to that one question, but nothing in this module
requires or reads that key.

Stdlib only — no third-party dependencies.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from external_write.contracts import SourceLineage


@dataclass(frozen=True)
class AdapterEvidence:
    """A single, already-materialized observation an evidence predicate
    evaluates. Immutable (frozen) — a predicate cannot mutate what it was
    handed, and no later code can retroactively alter evidence a predicate
    already evaluated.

    Attributes
    ----------
    op_kind:         The operation kind this evidence was captured for (e.g.
                     "gmail.message.trash", "set_status"). Predicates may use
                     this to sanity-check they were handed evidence for the
                     op_kind they think they are verifying, but a mismatch is
                     not detected here — this is a plain data field, not a
                     validated one at this layer.
    unit_id:         The EffectUnit identifier this evidence concerns (e.g. a
                     Gmail message id, a spreadsheet row key). Ties the
                     evidence to the specific mutation being checked, for a
                     multi-unit operation.
    poststate:       Opaque, adapter-defined mapping of OBSERVED facts after
                     the mutation (or after undo, when evaluating restore) —
                     e.g. a Gmail message's current label set / derived
                     flags, or a field's current value. Defaults to an empty
                     mapping (not every predicate needs poststate — an
                     undo-restore check may rely entirely on comparing
                     poststate to prestate, or an apply-landed check may not
                     need any prestate at all).
    prestate:        Optional opaque, adapter-defined mapping of the baseline
                     observed BEFORE the mutation — carried so an
                     undo-restored predicate can check poststate against it
                     (e.g. "does the current label set equal what was there
                     before trash?"). None when not applicable/not captured.
    source_lineage:  Declares where poststate/prestate came from — reusing
                     `contracts.SourceLineage` (the SAME vocabulary the
                     Authority-clause post-write verification record uses:
                     pre_write_sources / post_write_sources /
                     forbidden_verification_inputs). Required: every
                     AdapterEvidence must declare its lineage — this is the
                     "lineage-typed" half of the evidence object's name.
    """

    op_kind: str
    unit_id: str
    source_lineage: SourceLineage
    poststate: Mapping[str, Any] = field(default_factory=dict)
    prestate: Optional[Mapping[str, Any]] = None
