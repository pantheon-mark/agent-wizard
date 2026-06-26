"""Voice-settings derivation for the scaffold substitution map.

Derives the six voice keys (TONE / TECHNICAL_LEVEL / EXPLANATION_DEPTH /
LENGTH_PREFERENCE / LIST_STYLE / TABLE_STYLE) from `foundation_doc_inputs` and
returns them ready to inject via `**voice_settings_inputs(...)` into the
`scaffold_extra` dict.

Accepts two flavours of input:
  - Derived field names (live emit path, e.g. UP_TECHNICAL_LITERACY,
    NOTIFICATION_VERBOSITY, QA_REPORTING_STYLE) — what plan.foundation_doc_inputs
    carries at emit time.
  - Raw question IDs (UP-1, UP-4, ERR-1, QA-1) — the keys used in the brief's
    test skeleton; the function detects whichever flavour is present and reads from
    both so the function is useful in both test and live contexts.

Output values are drawn from the closed vocabulary in voice_and_style.md §4.2.
TONE is always "plain-and-direct" (project voice rule: never "warm").

Stdlib-only, pip-install-free.
"""

from typing import Dict


# Voice SOURCE fields. Injection is GATED on at least one of these being present
# in the input. They come in two flavours (see module docstring): derived field
# names produced by the v0.7.0 interview, and raw question IDs used in the brief's
# test skeleton. If NONE is present (e.g. a pre-v0.7.0 estate built before voice
# extraction existed), voice_settings_inputs returns an EMPTY dict so that
# `**voice_settings_inputs(...)` injects nothing and the scaffold placeholders fall
# back to their sentinel defaults — exactly as before voice injection was added.
# This keeps render(<released version>, <old capsule>) byte-for-byte reproducible so
# the replay-conformance gate does not see spurious drift on an old estate.
_VOICE_SOURCE_FIELDS = (
    "UP_TECHNICAL_LITERACY",
    "NOTIFICATION_VERBOSITY",
    "QA_REPORTING_STYLE",
    "UP-1",
    "UP-4",
    "ERR-1",
    "QA-1",
)


def voice_settings_inputs(inputs: Dict[str, str]) -> Dict[str, str]:
    """Derive the six voice keys from foundation_doc_inputs (or raw question IDs).

    Args:
        inputs: plan.foundation_doc_inputs or any dict containing voice-source keys.

    Returns:
        Empty dict when NONE of the voice source fields (`_VOICE_SOURCE_FIELDS`) is
        present — the caller injects nothing and the scaffold sentinels stand.
        Otherwise a dict with keys TONE, TECHNICAL_LEVEL, EXPLANATION_DEPTH,
        LENGTH_PREFERENCE, LIST_STYLE, TABLE_STYLE — all closed values.
    """
    # --- data-driven gate (replay-conformance fix) ---
    # Only inject voice values when the interview actually produced a voice source
    # field. A pre-v0.7.0 estate's capsule lacks all of them, so we inject nothing
    # and the released version's installed sentinel content re-renders unchanged.
    if not any(k in inputs for k in _VOICE_SOURCE_FIELDS):
        return {}

    # --- resolve source strings, preferring derived field names then raw IDs ---

    # TECHNICAL_LEVEL sources:
    #   derived: UP_TECHNICAL_LITERACY (scaffold field, set from UP-1 interview answer)
    #   raw:     UP-1 ("not technical" / "very technical" / "comfortable" / etc.)
    up_tech_raw = str(inputs.get("UP_TECHNICAL_LITERACY", inputs.get("UP-1", ""))).lower()

    # EXPLANATION_DEPTH sources:
    #   derived: NOTIFICATION_VERBOSITY ("Minimal"/"Standard"/"Detailed")
    #   raw:     ERR-1 ("quiet"/"standard"/"detailed") + UP-4 (verbosity preference)
    verbosity = str(inputs.get("NOTIFICATION_VERBOSITY", inputs.get("ERR-1", ""))).lower()
    up4 = str(inputs.get("UP-4", "")).lower()

    # LENGTH_PREFERENCE sources:
    #   derived: QA_REPORTING_STYLE ("summary"/"detailed")
    #   raw:     QA-1 ("concise"/"summary"/"detailed") + UP-4
    qa_style = str(inputs.get("QA_REPORTING_STYLE", inputs.get("QA-1", ""))).lower()

    # --- TECHNICAL_LEVEL ---
    if "not tech" in up_tech_raw or "non-tech" in up_tech_raw or "plain" in up_tech_raw:
        technical = "plain"
    elif (
        "very" in up_tech_raw
        or "comfortable" in up_tech_raw
        or "technical" in up_tech_raw
    ):
        technical = "technical"
    else:
        technical = "some-technical"

    # --- EXPLANATION_DEPTH ---
    if "minimal" in verbosity or "quiet" in verbosity or "brief" in up4:
        depth = "brief"
    elif "detailed" in verbosity or "detail" in up4:
        depth = "detailed"
    else:
        depth = "standard"

    # --- LENGTH_PREFERENCE ---
    # Closed vocabulary is concise / standard (no "detailed" length value), so a
    # detailed/live reporting style maps to standard like the default — the two are
    # folded into one else branch (M-1: the prior explicit "detailed"->"standard"
    # branch was dead, identical to the else).
    if "summary" in qa_style or "concise" in qa_style or "brief" in up4:
        length = "concise"
    else:
        length = "standard"

    return {
        "TONE": "plain-and-direct",           # project voice rule: never "warm"
        "TECHNICAL_LEVEL": technical,
        "EXPLANATION_DEPTH": depth,
        "LENGTH_PREFERENCE": length,
        "LIST_STYLE": "bullets",
        "TABLE_STYLE": "tables-when-comparing",
    }
